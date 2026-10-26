set -euo pipefail
cd "$(dirname "$0")"
esmc pll --in seqs.fasta --out /tmp/pll.tsv
esmc embed --in seqs.fasta --out /tmp/emb.npz
esmc fill --in masked.fasta --out /tmp/filled.fasta
python3 check.py /tmp/pll.tsv /tmp/emb.npz /tmp/filled.fasta
