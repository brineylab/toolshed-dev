# AGENTS.md

The lab's toolshed: published models and pipelines as self-contained OCI images, one prose skill per tool. A tool is an image with no entrypoint and a command-line program on its PATH; the caller supplies the command, and inputs and outputs are files in a mounted directory. The same image runs under podman on a laptop and under pyxis on a Slurm cluster.

Read before changing anything:

- `docs/VISION.md`: what the shed is for and what it is not.
- `docs/DESIGN.md`: what a tool is, the repository, the workflow, review.
- `docs/plans/toolshed-a.md`: the plan that builds the shed. Work it task by task; its Global Constraints are binding.
- `CONTRIBUTING.md`: how to add a tool, step by step. The rules below are the binding summary.

`docs/VISION.md` and `docs/DESIGN.md` are approved by the lab. Do not edit them unless asked to. If the work shows the design is wrong, stop and say so.

## Layout

```
tools/<name>/SKILL.md        the skill: what the tool is for, how to call it, what it needs
tools/<name>/Containerfile
tools/<name>/test/run.sh     plus a tiny fixture; exit 0 iff the tool works
tools/<name>/bin/            the wrapper program, only where upstream has none
results/<name>/<version>.txt the record of a candidate's test
scripts/check.py             a tool directory's rules, its candidate, its record, and whether its version is published
scripts/changed-tools <range>  the tools a git diff range changed, for CI
scripts/promote <repo> <candidate> <tested digest> <version>  copy the tested image to its version tag, never overwriting
scripts/build <name>         build the candidate, <name>:src-<tree>, for amd64 from committed source
scripts/push <name>          push it, first asking seed.yml to create a new tool's package, public and linked
scripts/test <name> podman|srun [flags]  test it by digest and write its record
scripts/record <name> <image@digest> <exit> <runner> <host> <started> < output  write a record from a test run some other way
tests/                       unit tests of the scripts, with registry, podman, srun, and skopeo stubbed
.github/workflows/tools.yml  check and promote, on hosted runners
.github/workflows/seed.yml   create a new tool's package, public and linked, with a placeholder
```

## Commands

```bash
python3 -I -m unittest discover tests          # the scripts' unit tests: the only tests the shed has
python3 -I scripts/check.py tools/<name>       # a tool's rules; add --registry ghcr.io/<owner>/<repo> for the version, candidate, and record
scripts/build <name> && scripts/push <name>     # from committed source; push needs gh signed in
scripts/test <name> srun --partition=<p> --gres=gpu:1 --time=00:30:00   # on a login node; or `podman` on a laptop
```

## Rules a tool must keep

- **Weights are in the image**, fetched at build time, never at run time. `HF_HUB_OFFLINE=1` (and `TRANSFORMERS_OFFLINE=1` with transformers) is set in the image. The test passes with `--network none`.
- **The Containerfile puts the environment first and the weights last**, then ends with `COPY test /toolshed/test`. Every package and base image is pinned.
- **A tool never carries a credential**: not in a file, not as an `ARG` or `ENV`; gated weights take the build secret. `scripts/build`, `scripts/record`, and `check` refuse what looks like one.
- **A GPU tool's image sets `NVIDIA_VISIBLE_DEVICES=all` and `NVIDIA_DRIVER_CAPABILITIES=compute,utility`**, on a glibc base, or pyxis gives it no GPU.
- **A Python tool loads its model from a path in the image, pinned to a revision, and runs under `python3 -I`**: pyxis passes the caller's environment and home in.
- **Every example in a skill is a full command line**, the program on PATH with its arguments. Pyxis ignores entrypoints.
- **Any change under `tools/<name>/` bumps `metadata.version`**, prose included. A published tag is never overwritten; callers always name a version.
- **The skill's frontmatter is `name` (the directory's), `description`, `metadata.version`.** Everything else is prose. No declared parameter lists.
- **A size variant is its own tool** (`esm2-650m`, `esmc-600m`): copy the sibling's directory and change the weights line and the skill's numbers.
- **The test runs the commands the skill documents** on a kilobyte fixture with a known answer, writes only under `/tmp`, and fits in one GPU and 30 minutes.
- **The wrapper in `bin/` is the only code the shed writes per tool**, and only where upstream ships no command-line program.

## Rules the shed keeps

- `scripts/` is Python stdlib (run with `python3 -I`; `check.py` must run on Python 3.8, since login nodes run it) or bash with `set -euo pipefail` that works under bash 3.2. No third-party package in the repository itself.
- Nothing in `scripts/` or `.github/` names the lab. The registry is `ghcr.io/${GITHUB_REPOSITORY,,}/<name>`, so a fork is its own shed with no edits.
- CI runs on hosted runners and never builds, pulls, or runs a tool image; `seed.yml` pushes only a `FROM scratch` placeholder. Whoever builds a tool tests its candidate where it will be used and commits the record; an agent cannot claim a tool works without one.
- No cluster ever builds an image. The contributor builds with `scripts/build`, from committed source.
- Every tool is reviewed by someone other than its builder before it merges.

## What not to build

A tool exists because a question needed it. Do not add tools, commands, or options speculatively. Not in the shed: datasets, analysis helpers (plotting, loaders), and anything that sequences tools. The items in `docs/DESIGN.md` §7 (a `toolshed` command, parameter schemas, private tools, CPU tests in CI, and the rest) are deferred until their stated trigger; do not build them early.

## Commits and pull requests

A commit message is one sentence stating the behavior. A tool arrives as a pull request whose record is committed with it. Merge with a merge commit (`gh pr merge --merge`): `promote` runs on the merge commit, and flyloft watches that check.
