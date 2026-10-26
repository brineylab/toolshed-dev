# Adding a tool

A tool is built because a question needs it. Before you start, `ls tools`: a sibling may be one size away from what you need.

## The layout

Copy the nearest sibling's directory to `tools/<name>/`, where `<name>` is lowercase words joined by hyphens, and change what differs.

- `SKILL.md`: the skill, the tool's whole description.
- `Containerfile`: the image.
- `test/run.sh`, with a tiny fixture beside it: exits 0 iff the tool works.
- `bin/`: the wrapper program, only where upstream ships no command-line program.

## The conventions

- **The environment first, the weights last**, then `COPY test /toolshed/test` as the last line. Size variants then share their base layers.
- **Weights are fetched at build time, never at run time.** Set `HF_HUB_OFFLINE=1` in the image, and `TRANSFORMERS_OFFLINE=1` where transformers is used.
- **A GPU tool sets `NVIDIA_VISIBLE_DEVICES=all` and `NVIDIA_DRIVER_CAPABILITIES=compute,utility`** in the image, on a glibc base. NVIDIA's CUDA images already do; a plain `python:*-slim` does not, and under pyxis it then sees no GPU though podman does.
- **A Python tool loads its model from a path in the image and runs under `python3 -I`**: download the weights with `snapshot_download(repo, revision=<commit>, local_dir=...)` and start the wrapper with `#!/usr/bin/env -S python3 -I`. Pyxis passes the caller's environment into the container, and their home with `~/.local`, so a caller's `HF_HUB_CACHE`, `PYTHONPATH`, or user packages would otherwise replace what was tested.
- **Pin everything**: the base image and every package, at the versions current when you build.
- **One image per size variant.** `esm2-650m` and a future `esm2-3b` are two tools; the second is a copy of the first with the weights line and the skill's numbers changed.
- **A wrapper only where upstream has none.** Where upstream is a library, `bin/` holds one short program exposing what the lab wants as subcommands (`esm2 pll`, `esm2 embed`). Where upstream ships a program (`boltz predict`), the image makes it runnable and the skill says which commands matter.
- **Every example in the skill is a full command line**: the program on the image's PATH with its arguments. Pyxis ignores entrypoints.

## The skill

Frontmatter has three fields a machine reads:

```markdown
---
name: <name>
description: <what it is for, and when to reach for it>
metadata:
  version: 1.0.0
---
```

`name` is the directory's name, `description` is the line the catalogue shows, and `metadata.version` is the image tag. The frontmatter is YAML: quote the description in double quotes when it holds a colon. Then the body, in this order: `Image:` (the full reference with its version), `## Commands`, `## Inputs and outputs`, `## Compute` (GPUs, memory, a measured rate), `## Running it` (the laptop line and the cluster line, with real commands), `## Gotchas`. No declared parameter lists: prose, until agents are seen misusing commands from it.

## The test

`test/run.sh` runs the commands the skill documents on a fixture of kilobytes with a known answer, and checks the answer. It exits 0 iff the tool works, writes only under `/tmp`, passes with no network, and fits in one GPU and 30 minutes. It checks the environment, the weights, and that the skill's examples are true, in one step.

## Building, pushing, and testing

You build your tool's image, push it, and test it where it will be used. CI never builds or runs an image.

1. **Commit** the tool directory. The image's tag is the candidate, `<name>:src-<tree>`, where `<tree>` is git's hash of the committed `tools/<name>/`, so `scripts/build` refuses uncommitted changes there.
2. **Build:** `scripts/build <name>`. It builds for `linux/amd64` (the clusters' architecture, even on an Apple Silicon Mac), labels the image with this repository, and prints the candidate's name.
3. **Try it:** `podman run --rm --network none <candidate> bash /toolshed/test/run.sh`.
4. **Push:** once per machine, `podman login ghcr.io` as yourself with a GitHub token that has `write:packages` (`gh auth refresh -s write:packages`, then `gh auth token | podman login ghcr.io -u <you> --password-stdin`). Then `scripts/push <name>`. A new tool's first push creates its package, which GitHub makes private. `scripts/push` says so and prints the package's settings link: make it public there, once, and under *Manage Actions access* make sure this repository has Write (add it if it is not listed), then run `scripts/push <name>` again. It exits 0 when the candidate can be pulled with no login.
5. **Test it where it will be used**, from a clone of your branch. On a cluster's login node:

   ```bash
   scripts/test <name> srun --partition=<partition> --gres=gpu:1 --time=00:30:00
   ```

   or `scripts/test <name> podman` where a laptop is where the tool will be used. It runs the candidate by digest and writes the record, `results/<name>/<version>.txt`: the digest, where it ran, the time, the output, and the exit code.
6. **Commit the record:** `git add results/<name>/<version>.txt`.

`python3 -I scripts/check.py tools/<name> --registry ghcr.io/<owner>/<repo>` runs CI's check on your machine.

A change after testing changes the tree, so build, push, and test again. A prose-only change that rebuilds from cache to the same digest may copy its earlier record to the new version's path, since the same image was tested.

## Versions

Any change under `tools/<name>/` bumps `metadata.version`, prose included. A published tag is never overwritten, and CI refuses a pull request whose version is already published.

## The pull request

1. Push your branch and open the pull request.
2. `check` runs: the tool's rules, an unpublished version, a public amd64 candidate for the branch's source, and a record of that candidate's passing test.
3. A member other than you reviews it: does the skill describe what the Containerfile builds, does the test exercise every documented command, are the weights in the image, is every example a full command line, and does the record show the test ran where the tool will be used and gave the known answers. They merge with a merge commit.
4. `promote` copies the candidate to `<name>:<version>`.

## Weights behind a login

For a gated Hugging Face repository, the build takes the token as a secret, never as an argument or a layer:

```dockerfile
RUN --mount=type=secret,id=hf_token HF_TOKEN=$(cat /run/secrets/hf_token) HF_HUB_OFFLINE=0 python -c "..."
```

Export `HF_TOKEN` before `scripts/build`, which passes it as the build secret. The token stays with whoever builds; it is never a GitHub secret.
