# The toolshed: Design

Status: approved 2026-10-23; amended 2026-10-23 so that contributors build and test candidates and CI never builds or runs one (§2); amended 2026-10-24 with what the first tool's test on the cluster showed (§1, §2); amended 2026-10-27 so that a new tool's package is created public by the shed's seed workflow, not made public by hand (§2), after a probe on a scratch shed showed a package its `GITHUB_TOKEN` created public, linked to the repository, and writable by a member's own token. The plan is [plans/toolshed-a.md](plans/toolshed-a.md). The flyloft side (calling tools from a campaign, building one when the shed lacks it) is designed in flyloft's repository, `docs/design/toolshed.md`; §6 below is its summary.

## 1. A tool

A tool is **an OCI image whose entrypoint is nothing and whose PATH holds a command-line program**: the image is the tool's environment, dependencies, and weights, and the caller supplies the command. Inputs and outputs are files in a directory the caller mounts. Nothing about a tool is Python-specific or flyloft-specific. The same image runs under `podman run` on a laptop, `docker run` where that is what exists, and `--container-image` on a Slurm cluster with pyxis.

- **One image per tool, many commands.** Where upstream ships a command-line program (`boltz predict`), the image makes it runnable and the skill says which commands matter. Where upstream is a library (ESM-2 through `transformers`, ESM-C through `esm`), the tool directory carries one short script exposing what the lab wants as subcommands of one program (`esm2 pll`, `esm2 embed`, `esm2 fill`). That script is the only code the shed writes per tool, and only when needed.
- **A size variant is a tool.** `esm2-650m`, `esmc-600m`, `boltz2`. The family is a naming convention, not a mechanism: a variant's directory is a copy of its sibling's with the weights line and the skill's numbers changed. Containerfiles put the environment first and the weights last, so variants share their base layers in the registry and on the nodes.
- **Weights are in the image**, fetched at build time, never at run time (`HF_HUB_OFFLINE=1` in the image). A version of a tool is one immutable thing. The ceiling is databases too big for an image (AlphaFold's); those belong to the data companion, not the shed.
- **A GPU tool asks for the driver.** Enroot mounts the node's driver only into an image that sets `NVIDIA_VISIBLE_DEVICES`, and the driver's `nvidia-smi` needs glibc. So a GPU tool's image sets `NVIDIA_VISIBLE_DEVICES=all` and `NVIDIA_DRIVER_CAPABILITIES=compute,utility` on a glibc base. NVIDIA's CUDA images already do; a plain `python:*-slim` or alpine base does not, and under pyxis it sees no GPU though podman with the GPU device does.
- **Every example in a skill is a full command line**, the program on the image's PATH with its arguments, never a bare argument to an entrypoint: pyxis ignores entrypoints and runs the job's command inside the container.
- **The image carries its own test.** The Containerfile copies the tool's `test/` directory to `/toolshed/test/`, so `bash /toolshed/test/run.sh` checks the image wherever it runs. The fixture is kilobytes.

**The skill** is the tool's whole description, prose in the Agent Skills format Claude Code, Codex, and OpenCode read:

```markdown
---
name: esm2-650m
description: "ESM-2 650M protein language model: per-residue embeddings, pseudo-log-likelihoods, and masked-position infilling for protein sequences. Reach for it for a sequence score or an embedding when a structure is not needed."
metadata:
  version: 1.0.0
---
# esm2-650m
Image: `ghcr.io/brineylab/toolshed/esm2-650m:1.0.0`
## Commands
## Inputs and outputs
## Compute
## Running it
## Gotchas
```

The frontmatter has three fields a machine reads: `name` (the directory's name), `description` (the catalogue line), and `metadata.version` (the image tag). Everything else is prose for the agent. No declared parameter lists; if agents are seen misusing commands from prose, that is the trigger for structure.

## 2. The repository

Public, one directory per tool:

```
README.md                 what the shed is; finding and running a tool from anywhere; installing the skills
CONTRIBUTING.md           adding a tool: the layout, the conventions, building, the test and its record, versions, the review
docs/                     this design, the vision, the plans
tools/<name>/SKILL.md     the skill (§1)
tools/<name>/Containerfile
tools/<name>/test/        run.sh and a tiny fixture: exits 0 iff the tool works
tools/<name>/bin/         the wrapper program, where upstream has none
results/<name>/<version>.txt   the record of the candidate's test: digest, where it ran, output, exit code
scripts/check.py          a tool directory's rules, its candidate, its record, and whether its version is already published
scripts/build <name>      podman build for linux/amd64, tagged as the candidate
scripts/push <name>       push the candidate; a new tool's package is first created by seed.yml
scripts/test <name>       the candidate's test, run by digest where the tool will be used, written to its record
scripts/record            a record from a test's output, for scripts/test and for a caller that ran the test itself (flyloft, through sbatch)
scripts/promote           copy a candidate to its version tag, never overwriting
.github/workflows/tools.yml
.github/workflows/seed.yml
```

**Versions.** `metadata.version` is the image tag, `ghcr.io/<owner>/<repo>/<name>:<version>`, with the owner and repository from the shed's own GitHub path, so a fork is its own shed and registry with no edits. A published tag is never overwritten: any change under `tools/<name>/` bumps the version, prose included, and CI refuses a pull request whose version is already in the registry. Callers always name a version, never a floating tag.

**The candidate** is the image a pull request proposes to publish, tagged `<name>:src-<tree>`, where `<tree>` is git's hash of the committed `tools/<name>/` directory (`git rev-parse HEAD:tools/<name>`). The tag names the source, so the image a pull request tested is the image its source describes, whatever else the branch does, and a rebase that leaves the directory alone leaves the tag alone. `scripts/build` refuses a directory with uncommitted changes, since the tag would then name source the image was not built from.

**The registry** is GHCR. Packages are public: free in storage and transfer, and pulled by enroot on cluster nodes and podman on laptops with no credential. GitHub fixes a package's visibility when it is created, from the credential that creates it: a member's token makes a private package, and no API changes that afterwards; a workflow's `GITHUB_TOKEN` in a public repository makes a public package linked to the repository, inheriting its permissions. So **a new tool's package is created by the shed's own workflow**: `seed.yml`, dispatched by `scripts/push` when the registry cannot serve the package anonymously, pushes a one-file placeholder tagged `seed`, and the contributor's push of the real candidate follows with their own credential. Nobody opens a package's settings. Later versions of the tool are tags in the same package and need nothing. `scripts/push` checks with an anonymous pull after pushing and, while the package is private (one created by a member's token before the seed workflow existed), prints the package's settings link and says so; `check` reports a candidate it cannot read anonymously as missing or not public. `scripts/build` names the shed's repository in each image's `org.opencontainers.image.source` label and manifest annotation (a base image's own annotation would otherwise win; alpine's names alpine's repository), which links a new package to the repository so that `promote`'s workflow token can write to it. The organization's package creation setting allows public packages (it once allowed only private ones). A tool whose license forbids redistribution is the exception, handled when it arrives (likely a squashfs on the cluster's shared storage), not designed for now.

**Building is the contributor's.** Whoever writes a tool builds it and pushes its candidate: a person on their own machine, flyloft on its own host (§6). Images with weights are 5 to 25 GB, which is why the building happens where there is disk, and why it is not CI's. Every image is `linux/amd64`, the clusters' architecture, whatever machine builds it. Pushing takes the contributor's own GitHub credential with package write access; only organization members can push to the organization's packages. A cluster is never asked to build: rootless podman on compute nodes is the one thing this design does not require of it, and enroot cannot build at all.

**The test** is the documented commands on a tiny fixture with a known answer, run inside the candidate: it checks the environment, the weights, and that the skill's examples are true, in one step. It must pass where the tool will be used, which for most tools is a cluster under pyxis, because that is where an image differs from `podman run`: entrypoints ignored, home mounted, the job's environment propagated, the node's driver. So the test is not CI's: CI has no GPU and no cluster. One GPU and 30 minutes is the expectation; the test passes with no network.

**The record.** `scripts/test <name>` resolves the candidate's tag to its digest, runs `bash /toolshed/test/run.sh` in the image by that digest (under `srun` with pyxis on a cluster's login node, or `podman run` on a laptop), and writes `results/<name>/<version>.txt`: the digest, the machine or cluster and partition, the GPU, the time, the command, its full output, and its exit code. Its job flags (partition, account, GPU request) are the caller's, passed through to `srun` and written into the record. Running by digest needs the cluster's enroot to accept `@sha256:` references; slinky's does (hello's test, 2026-10-24). A cluster whose enroot does not is handled when one arrives, by running the tag and failing if the digest it resolves before and after the job differ. The contributor commits the record to the pull request. The record lives outside `tools/<name>/`, so committing it does not change the candidate's tag. A record is a statement by whoever ran the test, not a proof; it guards against honest mistakes (testing an older image, not testing, testing somewhere the tool will not be used), which is what a shed with only the lab's contributors needs. A prose-only change that rebuilds from cache to the same digest can carry its earlier record forward under the new version, since the same image was tested.

**The workflow**, `tools.yml`, on hosted runners only, with the tools a pull request changes as its unit. It never builds, pulls, or runs an image; it reads the registry. `seed` pushes a placeholder that is not a tool.

- `seed`, `seed.yml`, on dispatch only, with `GITHUB_TOKEN`: the placeholder that creates a tool's package; it checks out nothing and runs no Containerfile.
- `check`, on every pull request: the skill's frontmatter parses and its name is the directory's; a Containerfile and `test/run.sh` exist; the version is not in the registry; the candidate `src-<tree>` is in the registry and is `linux/amd64`; the record exists for this version, names the candidate's digest, and shows exit code 0.
- `promote`, on a push to `main`, for the tools the push changed: the candidate tag, computed from the merge commit's tree, copied to the version tag (`skopeo copy` within the registry writes a manifest and moves no layers). A version tag that already holds the candidate's digest passes, so a re-run after a partial failure completes; one that holds anything else fails. It runs on the push, not on the pull request's close, so that its check attaches to the merge commit, which is what flyloft watches.

**Guards.** Nothing a pull request contains runs on the lab's machines: CI builds nothing and runs nothing but the check script and its unit test, on GitHub's hosted runners. A fork's pull request gets `check` with a read-only token and the public registry. What a published image contains is what an organization member built and pushed, as for any of the lab's code. The trust boundary is the organization's membership. `main` requires `check` to pass and takes no other required approval: flyloft merges as the campaign's owner, a member, after its critic's review, and a person's pull request is merged by a member other than its builder (§3).

**From a laptop.** The skill's `podman run` line is the interface. To give an agent the shed's skills: clone the repository and symlink each `tools/<name>` into the harness's skills directory (the README has the line). No `toolshed` command until the prose proves insufficient.

**Weights behind a login** (Hugging Face gated repositories): the Containerfile takes the token as a build secret, which `scripts/build` passes from the builder's `HF_TOKEN`. The token stays with whoever builds; it is never a GitHub secret.

## 3. Review

Every tool is reviewed by someone other than its builder before it is published: a lab member for a person's pull request, a flyloft critic for a campaign's. The reviewer asks: does the skill describe what the Containerfile builds, and is every command it documents exercised by the test; are the weights fetched at build time, so the image is self-contained; is every example a full command line; is the version new and the name the directory's; did the test run where the tool will be used, and does the record's output show the commands ran and gave the known answers. The reviewer never asks for more than a working, truthfully documented tool.

## 4. The first tools

`hello` (checks that a machine or cluster runs shed images), `esm2-650m`, and `esmc-600m`, built by hand. `boltz2` is the first tool a flyloft campaign builds. Sizes beyond these are added when a question asks for one.

## 5. Tests

The shed has no test tier of its own beyond the unit tests of its scripts: it is a repository, a workflow, and tools. Its acceptance is live, in [plans/toolshed-a.md](plans/toolshed-a.md): a contributor builds and pushes a candidate and its test passes on the cluster under pyxis, writing its record; `check` passes the pull request; merge promotes the tag; the published image runs from a laptop with the skill's line; a changed tool without a version bump is refused; a pull request whose record names another digest, or whose candidate is missing, is refused.

## 6. How flyloft uses the shed

Designed in flyloft's `docs/design/toolshed.md`. In short: flyloft keeps a clone at `origin/main` and renders the catalogue (name, version, description, skill path) into its implementers' assignments; a run may name `tool="name@version"`, and its job then runs inside the tool's image with the work directory mounted; an implementer that needs a tool the shed lacks writes it in a worktree of the shed and submits it; flyloft builds and pushes the candidate on its host, with `gh` signed in so that `scripts/push` can have the seed workflow create a new tool's package; runs `scripts/test` against it as a run of the campaign on the campaign's cluster and budget, commits the record, pushes the branch and opens the pull request, waits for `check`, has its critic review the pull request and the record, merges with a merge commit, and watches the merge commit's `promote` check; then the campaign calls the published version. One tool build at a time per campaign.

## 7. Deferred

| Item | Picked up |
|---|---|
| A private tool (a license that forbids redistribution): a squashfs on the cluster's shared storage | When one arrives |
| A `toolshed` command for laptops that picks podman or docker and mounts the working directory | When the skill's `podman run` line proves insufficient |
| Declared parameters per command | When agents are seen misusing commands from prose |
| Bulk databases (AlphaFold's) | The data companion's design |
| An image per GPU architecture (Arm) | When an Arm partition is wanted |
| A tool whose test needs more than one GPU or 30 minutes | When one is built |
| Retiring tools nobody calls: a count of callers | When the shed is big enough to need one |
| Running the test on CPU in CI where a tool allows it | When a broken candidate reaches a cluster often enough to matter |
| Signed test records (an in-toto test-result attestation attached to the candidate with cosign), so a record proves who vouched for it | When contributors from outside the lab arrive |
| Builds by CI on a builder the lab controls, so an image's contents do not depend on its contributor's machine | When contributors from outside the lab arrive, or builds by different machines are seen to differ |
