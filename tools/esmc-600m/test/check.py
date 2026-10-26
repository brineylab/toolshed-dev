"""check.py <pll.tsv> <emb.npz> <filled.fasta>: the outputs of test/run.sh have the shapes the skill documents."""
import math, sys

import numpy as np

pll_tsv, emb_npz, filled = sys.argv[1:]

rows = [line.rstrip("\n").split("\t") for line in open(pll_tsv)]
assert rows[0] == ["id", "pll"], rows[0]
assert [r[0] for r in rows[1:]] == ["peptide", "reversed"], rows
for _, v in rows[1:]:
    assert math.isfinite(float(v)) and float(v) < 0, v

emb = np.load(emb_npz)
assert emb["embeddings"].shape == (2, 1152) and emb["embeddings"].dtype == np.float32, emb["embeddings"].shape
assert list(emb["ids"]) == ["peptide", "reversed"], emb["ids"]

seq = open(filled).read().split("\n")[1]
assert "<mask>" not in seq and len(seq) == len("MKTAYIAK.RQISF.KSH"), seq
assert seq[:8] + seq[9:14] + seq[15:] == "MKTAYIAKRQISFKSH", seq
print("ok:", ", ".join(f"{r[0]} pll {r[1]}" for r in rows[1:]), "| filled", seq)
