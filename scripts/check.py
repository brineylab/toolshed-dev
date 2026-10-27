"""A tool directory's rules, its candidate, its record, and whether its version is already published.

    python3 -I scripts/check.py tools/<name>... [--registry ghcr.io/<owner>/<repo>]
    python3 -I scripts/check.py --candidate tools/<name>   prints <registry>/<name>:src-<tree>
    python3 -I scripts/check.py --resolve tools/<name>     prints <registry>/<name>@<digest>; exits 4 when not readable anonymously
    python3 -I scripts/check.py --published tools/<name>   exits 0 when the package is readable anonymously, else 4

Checking exits 0 when every directory passes, else prints one `tools/<name>: <reason>`
line per failure and exits 1. Without --registry the version, candidate, and record
rules are skipped. --candidate, --resolve, and --published take the registry from the origin remote
unless --registry is given. Runs on Python 3.8 or later, since a cluster's login node runs it.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def frontmatter(path: Path) -> dict:
    """The first `---` block: `key: value` lines, and `key:` opening a dict of two-space-indented lines.

    One pair of matching quotes around a value is removed. {} when there is no block.
    """
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out, nested = {}, None
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        if not line.strip():
            continue
        if line.startswith("  ") and nested is not None:
            key, _, value = line.strip().partition(":")
            nested[key.strip()] = unquote(value)
            continue
        key, _, value = line.partition(":")
        if value.strip():
            out[key.strip()], nested = unquote(value), None
        else:
            nested = out[key.strip()] = {}
    return {}  # no closing ---


def check_tool(tool_dir: Path, published: set[str] | None) -> list[str]:
    """The reasons this directory breaks the rules; empty when it passes."""
    name, reasons, version = tool_dir.name, [], None
    if not NAME.match(name):
        reasons.append(f"name {name!r} is not lowercase words joined by hyphens")
    skill = tool_dir / "SKILL.md"
    meta = frontmatter(skill) if skill.is_file() else None
    if meta is None:
        reasons.append("SKILL.md is missing")
    elif not meta:
        reasons.append("SKILL.md has no frontmatter block (--- ... ---)")
    else:
        if meta.get("name") != name:
            reasons.append(f"SKILL.md name {meta.get('name')!r} is not the directory's name {name!r}")
        if not meta.get("description"):
            reasons.append("SKILL.md description is empty")
        metadata = meta.get("metadata")
        version = metadata.get("version") if isinstance(metadata, dict) else None
        if not (isinstance(version, str) and VERSION.match(version)):
            reasons.append(f"SKILL.md metadata.version {version!r} is not MAJOR.MINOR.PATCH")
    containerfile = tool_dir / "Containerfile"
    if not containerfile.is_file():
        reasons.append("Containerfile is missing")
    elif "COPY test /toolshed/test" not in containerfile.read_text():
        reasons.append("Containerfile does not COPY test /toolshed/test")
    if not (tool_dir / "test" / "run.sh").is_file():
        reasons.append("test/run.sh is missing")
    if published is not None and version in published:
        reasons.append(f"version {version} is already published; bump metadata.version")
    return reasons


def check_candidate(tool_dir: Path, tag: str, candidate: tuple[str, str] | None) -> list[str]:
    """The reasons the candidate (its digest and architecture, or None when unreadable) or its record fail."""
    name = tool_dir.name
    if candidate is None:
        return [f"candidate {tag} is not in the registry or not public; push it with scripts/push {name} and make its package public"]
    digest, arch = candidate
    reasons = []
    if arch != "amd64":
        reasons.append(f"candidate {tag} is {arch}, not amd64; rebuild it with scripts/build {name}")
    version = frontmatter(tool_dir / "SKILL.md")["metadata"]["version"]
    rel = f"results/{name}/{version}.txt"
    path = tool_dir.parents[1] / rel
    if not path.is_file():
        return reasons + [f"{rel} is missing; test the candidate with scripts/test {name}"]
    rec = frontmatter(path)
    if rec.get("digest") != digest:
        reasons.append(f"{rel} is of {rec.get('digest')}, not the candidate {digest}; test the current candidate")
    if rec.get("exit") != "0":
        reasons.append(f"{rel} shows exit {rec.get('exit')}, not 0")
    return reasons


def registry_of(remote: str) -> str:
    """ghcr.io/<owner>/<repo>, lowercased, from a GitHub remote URL (https or ssh)."""
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", remote.strip())
    if not m:
        raise ValueError(f"not a GitHub remote: {remote}")
    return f"ghcr.io/{m.group(1).lower()}"


def candidate_tag(tool_dir: Path) -> str:
    """src-<git's hash of the committed tools/<name>/ directory>."""
    root = tool_dir.resolve().parents[1]
    tree = subprocess.run(["git", "-C", str(root), "rev-parse", f"HEAD:tools/{tool_dir.name}"],
                          check=True, capture_output=True, text=True).stdout.strip()
    return f"src-{tree}"


def _token(host: str, repo: str, name: str) -> str | None:
    """An anonymous pull token; None when refused, which is how GHCR answers a private or missing package."""
    try:
        with urllib.request.urlopen(f"https://{host}/token?scope=repository:{repo}/{name}:pull") as r:
            return json.load(r)["token"]
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            return None
        raise


ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


def inspect(registry: str, name: str, tag: str) -> tuple[str, str] | None:
    """The digest and architecture of <registry>/<name>:<tag>, anonymously; None when it cannot be read."""
    host, _, repo = registry.partition("/")
    token = _token(host, repo, name)
    if token is None:
        return None

    def get(path: str, accept: str | None = None):
        headers = {"Authorization": f"Bearer {token}"}
        if accept:
            headers["Accept"] = accept
        return urllib.request.urlopen(urllib.request.Request(f"https://{host}/v2/{repo}/{name}/{path}", headers=headers))

    try:
        with get(f"manifests/{tag}", ACCEPT) as r:
            digest, manifest = r.headers.get("Docker-Content-Digest"), json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            return None
        raise
    if "manifests" in manifest:  # an index: one entry per platform
        return digest, ",".join(m.get("platform", {}).get("architecture", "?") for m in manifest["manifests"])
    with get(f"blobs/{manifest['config']['digest']}") as r:
        return digest, json.load(r).get("architecture", "?")


def published_tags(registry: str, name: str) -> set[str]:
    """GHCR's tags for <registry>/<name>, anonymously; set() when the package does not exist.

    GHCR answers a package that does not exist with 403 at the token endpoint, and pages
    tags through the Link header.
    """
    host, _, repo = registry.partition("/")
    token = _token(host, repo, name)
    if token is None:
        return set()
    tags, path = set(), f"/v2/{repo}/{name}/tags/list?n=1000"
    while path:
        req = urllib.request.Request(f"https://{host}{path}", headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as r:
            tags |= set(json.load(r).get("tags") or [])
            link = re.match(r'<([^>]+)>;\s*rel="next"', r.headers.get("Link") or "")
        path = link and link.group(1)
    return tags


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tools", nargs="*", type=Path)
    p.add_argument("--registry")
    one = p.add_mutually_exclusive_group()
    one.add_argument("--candidate", type=Path, metavar="TOOL_DIR")
    one.add_argument("--resolve", type=Path, metavar="TOOL_DIR")
    one.add_argument("--published", type=Path, metavar="TOOL_DIR")
    args = p.parse_args()
    if args.candidate or args.resolve or args.published:
        d = args.candidate or args.resolve or args.published
        registry = (args.registry or registry_of(subprocess.run(
            ["git", "-C", str(d), "remote", "get-url", "origin"], check=True, capture_output=True, text=True).stdout)).lower()
        if args.published:  # scripts/push seeds a package this cannot read
            try:
                tags = published_tags(registry, d.name)
            except urllib.error.HTTPError as e:
                if e.code not in (401, 403, 404):
                    raise
                tags = set()
            if not tags:
                print(f"package {d.name} is not in the registry or not public", file=sys.stderr)
                return 4
            return 0
        tag = candidate_tag(d)
        if args.candidate:
            print(f"{registry}/{d.name}:{tag}")
            return 0
        found = inspect(registry, d.name, tag)
        if found is None:
            print(f"candidate {tag} is not in the registry or not public", file=sys.stderr)
            return 4  # distinct from a crash (1), so scripts/push can tell a private package from an error
        print(f"{registry}/{d.name}@{found[0]}")
        return 0
    failed = False
    for d in args.tools:
        ask = args.registry and NAME.match(d.name)  # an invalid name is already a failure, and GHCR rejects it
        published = published_tags(args.registry.lower(), d.name) if ask else None
        reasons = check_tool(d, published)
        if ask and not reasons:
            tag = candidate_tag(d)
            reasons = check_candidate(d, tag, inspect(args.registry.lower(), d.name, tag))
        for reason in reasons:
            print(f"tools/{d.name}: {reason}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
