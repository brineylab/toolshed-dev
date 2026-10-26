set -euo pipefail
cd "$(dirname "$0")"
out=$(mktemp -d)
esmc pll --in seqs.fasta --out "$out/pll.tsv"
esmc embed --in seqs.fasta --out "$out/emb.npz"
esmc fill --in masked.fasta --out "$out/filled.fasta"
python3 -I check.py "$out/pll.tsv" "$out/emb.npz" "$out/filled.fasta"
