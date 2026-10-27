"""check.py <out_dir>: boltz's outputs have the fields, ranking, and trained-weight behavior the skill documents."""
import json
import math
import sys
from pathlib import Path

import gemmi

OUT_FIELDS = ("confidence_score", "ptm", "iptm", "ligand_iptm", "protein_iptm",
              "complex_plddt", "complex_iplddt", "complex_pde", "complex_ipde")
RANGED = ("confidence_score", "ptm", "iptm", "protein_iptm", "complex_plddt")
N_SAMPLES = 5
# Each fixture is a homodimer run in single-sequence mode. complex is GCN4-p1,
# a 33-residue coiled-coil zipper: 66 residues, at or under cuequivariance's
# 100-residue crossover, so it runs the plain-PyTorch fallback. complex_large
# is HIV-1 protease (PDB 1HHP), a 99-residue obligate homodimer: 198 residues,
# past the crossover, so it runs the cuEquivariance Triton kernels that a
# larger complex needs, and only passes when the image can compile them.
FIXTURES = {
    "complex": "RMKQLEDKVEELLSKNYHLENEVARLKKLVGER",
    "complex_large": "PQITLWQRPLVTIKIGGQLKEALLDTGADDTVLEEMSLPGRWKPKMIGGIGGFIKVRQYDQILIEICGHKAIGTVLVGPTPVNIIGRNLLTQIGCTLNF",
}


def check_target(out_dir, name, seq):
    pred = out_dir / f"boltz_results_{name}" / "predictions" / name
    assert pred.is_dir(), f"no predictions directory under {out_dir}"

    cifs = sorted(pred.glob(f"{name}_model_*.cif"))
    assert len(cifs) == N_SAMPLES, f"expected {N_SAMPLES} structures, found {len(cifs)}: {[p.name for p in cifs]}"

    confs = {}
    for p in sorted(pred.glob(f"confidence_{name}_model_*.json")):
        d = json.loads(p.read_text())
        for k in OUT_FIELDS:
            assert k in d, (p.name, k)
            assert math.isfinite(d[k]), (p.name, k, d[k])
        for k in RANGED:
            assert 0.0 <= d[k] <= 1.0, (p.name, k, d[k])
        want = 0.8 * d["complex_plddt"] + 0.2 * d["iptm"]
        assert abs(d["confidence_score"] - want) < 1e-6, (p.name, d["confidence_score"], want)
        assert set(d["chains_ptm"]) == {"0", "1"}, (p.name, sorted(d["chains_ptm"]))
        assert set(d["pair_chains_iptm"]) == {"0", "1"}, (p.name, sorted(d["pair_chains_iptm"]))
        confs[p.name] = d
    assert len(confs) == N_SAMPLES, f"expected {N_SAMPLES} confidence jsons, found {len(confs)}"

    best = max(confs.values(), key=lambda d: d["confidence_score"])
    assert confs[f"confidence_{name}_model_0.json"]["confidence_score"] == best["confidence_score"], \
        "model_0 is not the highest-confidence sample: " + str({n: d["confidence_score"] for n, d in confs.items()})
    assert best["complex_plddt"] > 0.4, \
        f"{name}: best complex_plddt {best['complex_plddt']:.3f} is low for a known homodimer: the weights look untrained"

    doc = gemmi.cif.read(str(pred / f"{name}_model_0.cif"))
    tab = doc.sole_block().find("_atom_site.", ["label_atom_id", "label_asym_id"])
    assert len(tab) > 0, "model_0.cif holds no atom_site rows"
    ca = sum(1 for row in tab if row.str(0) == "CA")
    asym = {row.str(1) for row in tab}
    assert ca == 2 * len(seq), f"{ca} CA atoms, expected {2 * len(seq)} (both chains, every residue)"
    assert asym == {"A", "B"}, f"chains {asym}, expected A and B"

    return best


out_dir = Path(sys.argv[1])
for name, seq in FIXTURES.items():
    best = check_target(out_dir, name, seq)
    print(f"ok: {name}: {N_SAMPLES} samples, best confidence_score {best['confidence_score']:.4f} "
          f"(complex_plddt {best['complex_plddt']:.4f}, iptm {best['iptm']:.4f}), "
          f"2 chains x {len(seq)} residues")
