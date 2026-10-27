# toolshed

The lab's toolshed: published models and pipelines as self-contained container images, one prose skill per tool. A tool is a capability anyone in the lab, or any agent working for them, can call: a protein language model with its weights, a structure predictor, a molecular dynamics pipeline. Each tool is one image that holds its environment, its dependencies, and its weights, and one skill that says what it is for, how to call it, what it needs, and what to watch out for.

An image has no entrypoint and a command-line program on its PATH: the caller supplies the command, and inputs and outputs are files in a directory the caller mounts. The same image runs under podman on a laptop, under docker where that is what exists, and under pyxis on a Slurm cluster. Weights are fetched when the image is built, never when it runs, so a version of a tool is one immutable thing.

Why it exists and what it is not: [docs/VISION.md](docs/VISION.md). How it works: [docs/DESIGN.md](docs/DESIGN.md). Adding a tool: [CONTRIBUTING.md](CONTRIBUTING.md).

## Finding a tool

`ls tools`. Each `tools/<name>/SKILL.md` starts with what the tool is for and when to reach for it, then its image, its commands, its inputs and outputs, the compute it needs, and its gotchas.

## Running a tool from a laptop

```bash
podman run --rm --device nvidia.com/gpu=all -v "$PWD":/work -w /work \
  ghcr.io/brineylab/toolshed/<name>:<version> <command>
```

The GPU device needs the NVIDIA container toolkit's CDI spec, generated once: `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`. Without a GPU, drop `--device`. Where docker is what exists, `docker run --rm --gpus all -v "$PWD":/work -w /work ...` is the same line.

## On a Slurm cluster with pyxis

```bash
srun --gres=gpu:1 --container-image=ghcr.io#brineylab/toolshed/<name>:<version> \
  --container-mounts="$PWD":/work --container-workdir=/work <command>
```

The same flags work as `#SBATCH` lines. Mount every directory the command reads and writes. Pyxis ignores entrypoints, which is why every example in a skill is a full command line.

## Giving your coding agent the skills

```bash
git clone https://github.com/brineylab/toolshed && cd toolshed
mkdir -p ~/.claude/skills && for t in tools/*; do ln -sfn "$PWD/$t" ~/.claude/skills/; done
```

For Codex and OpenCode, link into `~/.agents/skills/` instead. `git pull` updates the linked skills; run the loop again after a pull that adds a tool.

## Checking an image

Every image carries its own test: `bash /toolshed/test/run.sh` inside it exits 0 iff the tool works there. On a new cluster, run the `hello` tool first.

## Versions

A tool's version is its image tag, and a published tag is never overwritten. Always name a version; there is no `latest`.

CI checks every pull request: the tool's rules, an unpublished version, a public amd64 candidate, and a record of that candidate's passing test. On merge it copies the candidate to `<name>:<version>`. CI never builds or runs a tool image: it checks, promotes, and creates a new tool's package with a placeholder.
