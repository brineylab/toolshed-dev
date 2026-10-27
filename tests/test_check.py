import unittest, tempfile, sys, io, json, urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check  # noqa: E402
from helpers import git  # noqa: E402

SKILL = "---\nname: {name}\ndescription: A tool.\nmetadata:\n  version: {version}\n---\n# {name}\n"

def tool(root: Path, name="esm2-650m", version="1.0.0", skill=True, containerfile="FROM x\nCOPY test /toolshed/test\n", run=True):
    d = root / "tools" / name
    (d / "test").mkdir(parents=True)
    if skill: (d / "SKILL.md").write_text(SKILL.format(name=name, version=version))
    if containerfile is not None: (d / "Containerfile").write_text(containerfile)
    if run: (d / "test" / "run.sh").write_text("set -euo pipefail\necho ok\n")
    return d

class CheckTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
    def test_frontmatter_parses_name_description_and_nested_version(self):
        d = tool(self.root)
        self.assertEqual(check.frontmatter(d / "SKILL.md"), {"name": "esm2-650m", "description": "A tool.", "metadata": {"version": "1.0.0"}})
    def test_a_good_tool_passes(self):
        self.assertEqual(check.check_tool(tool(self.root), published=set()), [])
    def test_every_rule_names_its_reason(self):
        cases = [
            (dict(name="Esm2"), "name"),                       # directory name not lowercase-hyphen
            (dict(version="1.0"), "metadata.version"),          # not semver
            (dict(skill=False), "SKILL.md"),
            (dict(containerfile=None), "Containerfile"),
            (dict(containerfile="FROM x\n"), "COPY test /toolshed/test"),
            (dict(run=False), "test/run.sh"),
        ]
        for kw, word in cases:
            root = Path(tempfile.mkdtemp())
            reasons = check.check_tool(tool(root, **kw), published=set())
            self.assertTrue(any(word in r for r in reasons), (kw, reasons))
    def test_a_skill_whose_name_is_not_the_directorys_fails(self):
        d = tool(self.root)
        (d / "SKILL.md").write_text(SKILL.format(name="other", version="1.0.0"))
        self.assertTrue(any("name" in r for r in check.check_tool(d, published=set())))
    def test_a_published_version_is_refused(self):
        reasons = check.check_tool(tool(self.root), published={"1.0.0"})
        self.assertEqual(reasons, ["version 1.0.0 is already published; bump metadata.version"])
    def test_a_tool_holding_a_credential_is_refused_with_the_file_and_line(self):
        cases = [  # (what to write, where, the words the reason must hold)
            ("export HF_TOKEN=hf_" + "a" * 34 + "\n", "bin/x", ("bin/x:1", "Hugging Face token", "build secret", "revoke")),
            ("FROM x\nARG HF_TOKEN\nCOPY test /toolshed/test\n", "Containerfile", ("Containerfile:2", "ARG HF_TOKEN", "history", "revoke")),
            ("FROM x\nENV HF_HUB_OFFLINE=1 \\\n    HF_TOKEN=abc\nCOPY test /toolshed/test\n", "Containerfile", ("Containerfile:2", "ENV HF_TOKEN")),
            ("export WANDB_API_KEY=" + "0" * 40 + "\n", "test/run.sh", ("test/run.sh:1", "password or token")),
            ('{"token": "' + "t" * 21 + '"}\n', "test/cfg.json", ("test/cfg.json:1", "password or token")),
            ("FROM x\nENV GITHUB_TOKEN=abc\nCOPY test /toolshed/test\n", "Containerfile", ("Containerfile:2", "ENV GITHUB_TOKEN")),
            ("FROM x\nENV HF_HUB_OFFLINE=1 HF_TOKEN=abc\nCOPY test /toolshed/test\n", "Containerfile", ("Containerfile:2", "ENV HF_TOKEN")),
            ("-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n", "test/fixture.txt", ("test/fixture.txt:1", "private key")),
            ('password = "' + "p" * 20 + '"\n', "bin/x", ("bin/x:1", "password or token")),
            ("machine api.example login me password x\n", "test/.netrc", ("test/.netrc", "credential file by name", "revoke")),
            ("AKIAIOSFODNN7EXAMPLE\n", "test/run.sh", ("test/run.sh:1", "AWS")),
        ]
        for text, where, words in cases:
            d = tool(Path(tempfile.mkdtemp()))
            (d / where).parent.mkdir(parents=True, exist_ok=True)
            (d / where).write_text(text)
            reasons = check.check_tool(d, published=set())
            self.assertTrue(any(all(w in r for w in words) for r in reasons), (where, reasons))
    def test_the_secret_mount_prose_and_binary_fixtures_pass(self):
        d = tool(self.root, containerfile=(
            "FROM x\nRUN --mount=type=secret,id=hf_token HF_TOKEN=$(cat /run/secrets/hf_token) HF_HUB_OFFLINE=0 python -c 'x'\n"
            "ENV HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false\nCOPY test /toolshed/test\n"))
        (d / "SKILL.md").write_text(SKILL.format(name="esm2-650m", version="1.0.0") + "The token stays with whoever builds. password: see the README. max_tokens: 12345678901234567890\n")
        (d / "test" / "weights.npz").write_bytes(b"\x00PK" + b"hf_" + b"a" * 40)
        self.assertEqual(check.check_tool(d, published=set()), [])

class FrontmatterTests(unittest.TestCase):
    def test_quoted_values_are_unquoted(self):
        d = tool(Path(tempfile.mkdtemp()))
        (d / "SKILL.md").write_text('---\nname: esm2-650m\ndescription: "ESM-2: a model."\nmetadata:\n  version: \'1.0.0\'\n---\n')
        self.assertEqual(check.frontmatter(d / "SKILL.md"), {"name": "esm2-650m", "description": "ESM-2: a model.", "metadata": {"version": "1.0.0"}})
        self.assertEqual(check.check_tool(d, published=set()), [])
    def test_a_skill_without_frontmatter_gets_one_reason(self):
        d = tool(Path(tempfile.mkdtemp()))
        (d / "SKILL.md").write_text("---\nname: esm2-650m\n# no closing line\n")
        self.assertEqual(check.check_tool(d, published=set()), ["SKILL.md has no frontmatter block (--- ... ---)"])

def record(root, name="esm2-650m", version="1.0.0", digest="sha256:a", exit="0"):
    r = root / "results" / name / f"{version}.txt"
    r.parent.mkdir(parents=True, exist_ok=True)
    r.write_text(f"---\ntool: {name}\nversion: {version}\ndigest: {digest}\nexit: {exit}\n---\nok\n")

class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()); self.d = tool(self.root)
    def reasons(self, candidate):
        return check.check_candidate(self.d, "src-x", candidate)
    def test_registry_of_https_and_ssh_remotes(self):
        for url in ("https://github.com/BrineyLab/ToolShed.git", "https://github.com/BrineyLab/ToolShed", "git@github.com:BrineyLab/ToolShed.git"):
            self.assertEqual(check.registry_of(url), "ghcr.io/brineylab/toolshed")
    def test_candidate_tag_is_the_committed_tree(self):
        git(self.root, "init", "-q"); git(self.root, "add", "-A"); git(self.root, "commit", "-qm", "x")
        tree = git(self.root, "rev-parse", "HEAD:tools/esm2-650m").strip()
        self.assertEqual(check.candidate_tag(self.d), f"src-{tree}")
    def test_a_good_candidate_and_record_pass(self):
        record(self.root)
        self.assertEqual(self.reasons(("sha256:a", "amd64")), [])
    def test_a_candidate_not_readable_anonymously_is_reported(self):
        self.assertEqual(self.reasons(None), ["candidate src-x is not in the registry or not public; push it with scripts/push esm2-650m and make its package public"])
    def test_a_candidate_not_amd64_is_refused(self):
        record(self.root)
        self.assertEqual(self.reasons(("sha256:a", "arm64")), ["candidate src-x is arm64, not amd64; rebuild it with scripts/build esm2-650m"])
    def test_a_missing_record_is_refused(self):
        self.assertEqual(self.reasons(("sha256:a", "amd64")), ["results/esm2-650m/1.0.0.txt is missing; test the candidate with scripts/test esm2-650m"])
    def test_a_record_of_another_digest_is_refused(self):
        record(self.root, digest="sha256:old")
        self.assertEqual(self.reasons(("sha256:a", "amd64")), ["results/esm2-650m/1.0.0.txt is of sha256:old, not the candidate sha256:a; test the current candidate"])
    def test_a_record_with_bytes_that_are_not_utf8_still_reads(self):
        record(self.root)
        r = self.root / "results/esm2-650m/1.0.0.txt"
        r.write_bytes(r.read_bytes() + b"\xff\xfe progress\n")
        self.assertEqual(self.reasons(("sha256:a", "amd64")), [])
    def test_a_failed_record_is_refused(self):
        record(self.root, exit="1")
        self.assertEqual(self.reasons(("sha256:a", "amd64")), ["results/esm2-650m/1.0.0.txt shows exit 1, not 0"])
    def test_a_record_holding_a_prefixed_credential_from_the_jobs_environment_is_refused(self):
        record(self.root)
        r = self.root / "results/esm2-650m/1.0.0.txt"
        r.write_text(r.read_text() + "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n")
        self.assertEqual(len(self.reasons(("sha256:a", "amd64"))), 1)
    def test_a_record_holding_a_credential_is_refused(self):
        record(self.root)
        r = self.root / "results/esm2-650m/1.0.0.txt"
        r.write_text(r.read_text() + "GITHUB_TOKEN=ghp_" + "x" * 36 + "\n")
        self.assertEqual(self.reasons(("sha256:a", "amd64")), ["results/esm2-650m/1.0.0.txt:8 holds what looks like a GitHub token; the test's output must not print a credential or the job's environment"])

class Response(io.BytesIO):
    def __init__(self, body, link=None, headers=None):
        super().__init__(json.dumps(body).encode())
        self.headers = {"Link": link} if link else {}
        self.headers.update(headers or {})

class PublishedTagsTests(unittest.TestCase):
    def stub(self, fake):
        real = check.urllib.request.urlopen
        check.urllib.request.urlopen = fake
        self.addCleanup(setattr, check.urllib.request, "urlopen", real)
    def test_every_page_of_tags_is_read(self):
        pages = {"/v2/o/r/t/tags/list?n=1000": Response({"tags": ["1.0.0"]}, '</v2/o/r/t/tags/list?last=1.0.0&n=1000>; rel="next"'),
                 "/v2/o/r/t/tags/list?last=1.0.0&n=1000": Response({"tags": ["2.0.0"]})}
        def fake(req):
            url = req if isinstance(req, str) else req.full_url
            return Response({"token": "x"}) if "/token?" in url else pages[url.removeprefix("https://ghcr.io")]
        self.stub(fake)
        self.assertEqual(check.published_tags("ghcr.io/o/r", "t"), {"1.0.0", "2.0.0"})
    def test_a_package_that_does_not_exist_has_no_tags(self):
        def fake(req):  # GHCR refuses an anonymous token for a package that does not exist
            raise urllib.error.HTTPError(str(req), 403, "Forbidden", {}, None)
        self.stub(fake)
        self.assertEqual(check.published_tags("ghcr.io/o/r", "t"), set())
    def test_inspect_reads_digest_and_architecture(self):
        def fake(req):
            url = req if isinstance(req, str) else req.full_url
            if "/token?" in url:
                return Response({"token": "x"})
            if url.endswith("/v2/o/r/t/manifests/src-x"):
                return Response({"mediaType": "application/vnd.oci.image.manifest.v1+json", "config": {"digest": "sha256:c"}},
                                headers={"Docker-Content-Digest": "sha256:m"})
            if url.endswith("/v2/o/r/t/blobs/sha256:c"):
                return Response({"architecture": "amd64"})
            raise AssertionError(url)
        self.stub(fake)
        self.assertEqual(check.inspect("ghcr.io/o/r", "t", "src-x"), ("sha256:m", "amd64"))
    def test_inspect_of_a_private_or_missing_candidate_is_none(self):
        def refused_token(req):
            raise urllib.error.HTTPError(str(req), 403, "Forbidden", {}, None)
        self.stub(refused_token)
        self.assertIsNone(check.inspect("ghcr.io/o/r", "t", "src-x"))
        def missing_manifest(req):
            url = req if isinstance(req, str) else req.full_url
            if "/token?" in url:
                return Response({"token": "x"})
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        self.stub(missing_manifest)
        self.assertIsNone(check.inspect("ghcr.io/o/r", "t", "src-x"))
    def main(self, *args):
        out = io.StringIO()
        argv, stdout, stderr = sys.argv, sys.stdout, sys.stderr
        sys.argv, sys.stdout, sys.stderr = ["check.py", *args, "--registry", "ghcr.io/o/r"], out, io.StringIO()
        try:
            return check.main(), out.getvalue(), sys.stderr.getvalue()
        finally:
            sys.argv, sys.stdout, sys.stderr = argv, stdout, stderr
    def test_a_bad_name_is_reported_without_asking_the_registry(self):
        def fake(req):
            raise AssertionError("registry asked about an invalid name")
        self.stub(fake)
        d = tool(Path(tempfile.mkdtemp()), name="Esm2")
        code, out, _ = self.main(str(d))
        self.assertEqual(code, 1)
        self.assertIn("tools/Esm2: name", out)
    def test_published_exits_0_when_the_package_can_be_read(self):
        self.stub(lambda req: Response({"token": "x"} if "/token?" in (req if isinstance(req, str) else req.full_url) else {"tags": ["seed"]}))
        self.assertEqual(self.main("--published", "tools/t")[0], 0)
    def test_published_exits_4_when_the_package_is_missing_or_private(self):
        def refused_token(req):
            raise urllib.error.HTTPError(str(req), 403, "Forbidden", {}, None)
        self.stub(refused_token)
        self.assertEqual(self.main("--published", "tools/t")[0], 4)
        def refused_tags(req):
            url = req if isinstance(req, str) else req.full_url
            if "/token?" in url:
                return Response({"token": "x"})
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
        self.stub(refused_tags)
        self.assertEqual(self.main("--published", "tools/t")[0], 4)
    def test_scan_prints_hits_to_stderr_and_exits_1(self):
        p = Path(tempfile.mkdtemp()) / "r.txt"
        p.write_text("ok\nhf_" + "b" * 34 + "\n")
        code, _, err = self.main("--scan", str(p))
        self.assertEqual(code, 1)
        self.assertIn("r.txt:2 holds what looks like a Hugging Face token", err)
        p.write_text("ok\n")
        self.assertEqual(self.main("--scan", str(p))[0], 0)

if __name__ == "__main__":
    unittest.main()
