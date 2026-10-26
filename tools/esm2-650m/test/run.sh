set -euo pipefail
cd "$(dirname "$0")"
out=$(mktemp -d)
esm2 pll --in seqs.fasta --out "$out/pll.tsv"
esm2 embed --in seqs.fasta --out "$out/emb.npz"
esm2 fill --in masked.fasta --out "$out/filled.fasta"
python3 -I check.py "$out/pll.tsv" "$out/emb.npz" "$out/filled.fasta"
