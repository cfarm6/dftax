#!/usr/bin/env python3
"""Smoke-check stored inventory: derived counts, set reconciliation, coverage."""
import json
import sys
p = sys.argv[1] if len(sys.argv) > 1 else "whole-catalog-inventory.json"
inv = json.load(open(p))
rows = inv["rows"]
ids = [r["id"] for r in rows]
assert len(rows) == 709, len(rows)
assert len(set(ids)) == 709
names = set()
for r in rows:
    names.update(r["aliases"])
print(f"identities=709 unique=709 names={len(names)} "
      f"primal={sum(1 for r in rows if r['cls']=='primal')} "
      f"mix_only={sum(1 for r in rows if r['cls']=='mix_only')}")
# derived group sets from row predicates (exact set equality, not lengths)
def pred_semilocal(r):
    return (r["cls"] == "primal" and r["energy_spin1"] == "ok"
            and r["family"] in ("LDA", "GGA", "MGGA") and r["dim"] == "3D"
            and r["kind"] != "KINETIC" and not r["needs_laplacian"]
            and not r["vv10"])
def pred_global(r):
    return (r["family"] in ("HYB_LDA", "HYB_GGA", "HYB_MGGA")
            and not r["hyb_cam"] and not r["hyb_camy"])
expected = {
    "semilocal_3d_energy": {r["id"] for r in rows if pred_semilocal(r)},
    "laplacian_needs": {r["id"] for r in rows if r["needs_laplacian"]},
    "global_hybrid": {r["id"] for r in rows if pred_global(r)},
    "range_separated_erf_CAM": {r["id"] for r in rows if r["hyb_cam"]},
    "yukawa_CAMY": {r["id"] for r in rows if r["hyb_camy"]},
    "nonlocal_VV10": {r["id"] for r in rows if r["vv10"]},
    "kinetic": {r["id"] for r in rows if r["kind"] == "KINETIC"},
    "non3d": {r["id"] for r in rows if r["dim"] != "3D"},
    "development": {r["id"] for r in rows if r["development"]},
    "potential_only": {r["id"] for r in rows
                       if r["energy_spin1"] == "NO_EXC_POTENTIAL_ONLY"},
    "thermal_finite_T": {259, 318, 577},
    "multicomponent_epc": {328, 329, 330, 331},
    "spline_opaque_CASE21": {390},
    "enforce_fhc": {r["id"] for r in rows if r["enforce_fhc"]},
    "composites_mix_only": {r["id"] for r in rows
                            if r["cls"] == "mix_only"},
}
row_ids = {r["id"] for r in rows}
byid = {r["id"]: r for r in rows}
assert {i for i in row_ids
        if byid[i]["operator_class"] == "finite-T free energy"} == {259, 318, 577}
assert {i for i in row_ids
        if byid[i]["operator_class"] == "multicomponent electron-proton"} == {328, 329, 330, 331}
for k, v in inv["groups"].items():
    assert k in expected, k
    stored = set(v)
    assert stored <= row_ids, (k, sorted(stored - row_ids))
    assert stored == expected[k], (
        k, sorted(stored ^ expected[k])[:10])
assert set(inv["groups"]) == set(expected), (
    set(inv["groups"]) ^ set(expected))
derived = {k: len(v) for k, v in expected.items()}
covered = set()
for v in inv["groups"].values():
    covered.update(v)
plain = [r["id"] for r in rows if r["id"] not in covered]
byid = {r["id"]: r for r in rows}
assert not plain or all(
    byid[i]["family"] in ("LDA", "GGA", "MGGA") for i in plain), plain
print("derived:", derived)
print(f"covered={len(covered)} plain-semilocal-uncovered={len(plain)}")
for k, v in inv["groups"].items():
    print(f"{k}: {len(v)}")
print("OK")
