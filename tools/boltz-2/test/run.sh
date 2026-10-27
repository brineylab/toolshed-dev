set -euo pipefail
cd "$(dirname "$0")"
out=$(mktemp -d)
boltz predict complex.yaml --out_dir "$out" --diffusion_samples 5 --seed 0
boltz predict complex_large.yaml --out_dir "$out" --diffusion_samples 5 --seed 0
python3 -I check.py "$out"
