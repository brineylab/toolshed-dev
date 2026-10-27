---
name: boltz-2
description: "Boltz-2 complex structure and confidence prediction: jointly folds a multi-chain complex, such as a paired antibody's heavy and light chain, from sequences alone, and reports an overall confidence score per sample. Reach for it when a complex's structure or confidence is needed without an MSA."
metadata:
  version: 1.0.1
---
# boltz-2

Image: `ghcr.io/brineylab/toolshed/boltz-2:1.0.1`

Boltz-2, the open-source biomolecular interaction model (the `boltz` package, version 2.2.1 on PyPI, from the Boltz line of models out of MIT and Baidu research; MIT licensed), run through its own `boltz predict` program on PyTorch 2.7.1 (the CUDA 12.6 image) with the cuEquivariance kernels at 0.6.1, the release current when boltz 2.2.1 shipped. The weights and CCD data from Hugging Face's `boltz-community/boltz-2` at revision `6fdef46d763fee7fbb83ca5501ccceff43b85607` (`boltz2_conf.ckpt`, the affinity checkpoint `boltz2_aff.ckpt`, and `mols.tar`, extracted) are in the image at `$BOLTZ_CACHE` (`/opt/boltz-cache`); it needs no network.

## Commands

```bash
boltz predict complex.yaml --out_dir out --diffusion_samples 5 --seed 0
```

The input is a YAML file, or a directory of them, describing the complex; `--out_dir` receives a `boltz_results_<input-stem>` directory. `--diffusion_samples` is how many structures to sample per input (default 1); `--seed` fixes the random seed; `--recycling_steps` (default 3) and `--sampling_steps` (default 200) trade speed for quality; `--output_format pdb` writes PDB instead of mmCIF; `--override` redoes inputs whose predictions already exist in the output directory, which without the flag are skipped, so an interrupted batch resumes where it stopped; `--use_msa_server` generates MSAs with the mmseqs2/ColabFold API. `boltz predict --help` lists every option.

## Inputs and outputs

- **In:** a YAML file naming the complex's chains. Protein chains carry a unique `id`, a `sequence`, and an MSA: a path to an `.a3m`/CSV file, or `empty` for single-sequence mode (no MSA, no server). Identical chains share one entry with a list of ids. Ligands (`ccd`/`smiles`), DNA/RNA, constraints, templates, and affinity properties follow the upstream schema (github.com/jwohlwend/boltz). A minimal two-chain complex:

```yaml
version: 1
sequences:
  - protein:
      id: A
      sequence: MKTAYIAKQRQISFVKSH
      msa: empty
  - protein:
      id: B
      sequence: MKTAYIAKQRQISFVKSH
      msa: empty
```

- **Out:** under `--out_dir`'s `boltz_results_<input-stem>/predictions/<input-stem>/`, one `<input-stem>_model_<i>.cif` per sample — ranked, `model_0` the most confident — each beside `confidence_<input-stem>_model_<i>.json` holding `confidence_score`, `ptm`, `iptm`, `ligand_iptm`, `protein_iptm`, `complex_plddt`, `complex_iplddt`, `complex_pde`, `complex_ipde`, `chains_ptm`, and `pair_chains_iptm`, and `plddt_<input-stem>_model_<i>.npz` holding per-token pLDDT. `confidence_score` is Boltz's native overall score for the whole complex, `0.8 × complex_plddt + 0.2 × iptm` (`ptm` in place of `iptm` for single chains), on [0, 1], higher meaning more confident; Boltz ranks its samples by it. It is not a binding affinity and not an experimentally measured accuracy.

## Compute

One GPU. The 3 GB checkpoint and CCD data load in about a minute, and small complexes take a few GB of GPU memory, growing with residue count: a two-chain antibody pair of roughly 700 residues with 5 samples fits an L40S (48 GB). On an L40S, the fixtures of this tool's test (a 66-residue and a 198-residue two-chain complex, each with 5 samples at default steps) finish within minutes; antibody-scale pairs take tens of minutes. Every protein chain without an MSA runs single-sequence, at some cost in accuracy.

## Running it

On a laptop, from the directory holding `complex.yaml` (drop `--device`-style flags; there are none):

```bash
podman run --rm --device nvidia.com/gpu=all -v "$PWD":/work -w /work \
  ghcr.io/brineylab/toolshed/boltz-2:1.0.1 boltz predict complex.yaml --out_dir out --diffusion_samples 5 --seed 0
```

On a Slurm cluster with pyxis:

```bash
srun --gres=gpu:1 --container-image=ghcr.io#brineylab/toolshed/boltz-2:1.0.1 \
  --container-mounts="$PWD":/work --container-workdir=/work boltz predict complex.yaml --out_dir out --diffusion_samples 5 --seed 0
```

## Gotchas

- Single-sequence mode (`msa: empty`) uses no MSA and no network, at a cost in accuracy; it is the mode for a sequence with no MSA at hand.
- Without `--override`, an input whose `predictions/<id>/` folder already exists in the output directory is skipped, and the preprocessed inputs are cached too, so a rerun of an interrupted batch picks up where it stopped.
- `--use_msa_server` needs the network and the public ColabFold API; nothing else this skill shows does.
- The affinity checkpoint is carried only so that nothing downloads at run time; affinity predictions (YAML `properties: affinity` on a small-molecule binder) are not exercised by this tool's test.
- On GPUs older than Ampere, pass `--no_kernels` to disable the cuEquivariance kernels.
- Complexes of more than 100 residues in total run Boltz's cuEquivariance Triton kernels (cuequivariance's crossover, `CUEQ_TRIMUL_FALLBACK_THRESHOLD`/`CUEQ_TRIATTN_FALLBACK_THRESHOLD`, both 100; complexes of 100 or fewer fall back to plain PyTorch ops). Triton compiles a small C driver shim on first use, so the image installs gcc: the stock pytorch runtime base carries no C compiler, and without one prediction of a larger complex dies at the first kernel with `Failed to find C compiler. Please specify via CC environment variable.`
- The cuEquivariance stack is pinned at 0.6.1 on purpose: every release from 0.11.1 requires torch>=2.11, which this image's torch 2.7.1 — the version boltz 2.2.1 and its pytorch-lightning 2.5.0 pin were current with — does not satisfy.
- Predictions are named after the input file's stem, so `complex.yaml` yields `boltz_results_complex/predictions/complex/`.
