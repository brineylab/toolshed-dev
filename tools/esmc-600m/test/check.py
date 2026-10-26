"""check.py <pll.tsv> <emb.npz> <filled.fasta>: the outputs of test/run.sh have the shapes the skill documents, from trained weights."""
import math, sys

import numpy as np

# Ubiquitin's pll per residue: trained ESM-2 650M -0.58 and ESM C 600M -0.05; the same models untrained -3.5 and -4.3.
PLL_FLOOR = -1.5
IDS = ["peptide", "reversed", "ubiquitin"]

pll_tsv, emb_npz, filled = sys.argv[1:]

rows = [line.rstrip("\n").split("\t") for line in open(pll_tsv)]
assert rows[0] == ["id", "pll"], rows[0]
assert [r[0] for r in rows[1:]] == IDS, rows
for _, v in rows[1:]:
    assert math.isfinite(float(v)) and float(v) < 0, v
per_residue = float(rows[3][1]) / 76
assert per_residue > PLL_FLOOR, f"ubiquitin pll per residue {per_residue:.2f} is below {PLL_FLOOR}: the weights look untrained"

emb = np.load(emb_npz)
assert emb["embeddings"].shape == (3, 1152) and emb["embeddings"].dtype == np.float32, emb["embeddings"].shape
assert list(emb["ids"]) == IDS, emb["ids"]

seq = open(filled).read().split("\n")[1]
assert "<mask>" not in seq and len(seq) == len("MKTAYIAK.RQISF.KSH"), seq
assert seq[:8] + seq[9:14] + seq[15:] == "MKTAYIAKRQISFKSH", seq
print("ok:", ", ".join(f"{r[0]} pll {r[1]}" for r in rows[1:]), f"| ubiquitin {per_residue:.2f}/residue | filled", seq)
