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
# derived group counts from row predicates (not stored group lists)
derived = {
    "kinetic": sum(1 for r in rows if r["kind"] == "KINETIC"),
    "non3d": sum(1 for r in rows if r["dim"] != "3D"),
    "laplacian": sum(1 for r in rows if r["needs_laplacian"]),
    "cam": sum(1 for r in rows if r["hyb_cam"]),
    "camy": sum(1 for r in rows if r["hyb_camy"]),
    "vv10": sum(1 for r in rows if r["vv10"]),
    "dev": sum(1 for r in rows if r["development"]),
    "potonly": sum(1 for r in rows
                   if r["energy_spin1"] == "NO_EXC_POTENTIAL_ONLY"),
}
stored = {k: len(v) for k, v in inv["groups"].items()}
assert derived["kinetic"] == stored["kinetic"], derived
assert derived["non3d"] == stored["non3d"], derived
assert derived["laplacian"] == stored["laplacian_needs"], derived
assert derived["cam"] == stored["range_separated_erf_CAM"], derived
assert derived["camy"] == stored["yukawa_CAMY"], derived
assert derived["vv10"] == stored["nonlocal_VV10"], derived
assert derived["dev"] == stored["development"], derived
assert derived["potonly"] == stored["potential_only"], derived
# every row classified: in >=1 group beyond the raw census
covered = set()
for v in inv["groups"].values():
    covered.update(v)
plain = [r["id"] for r in rows if r["id"] not in covered]
plain_ok = [i for i in plain if {r["id"]: r for r in rows}[i]["cls"] == "primal"]
assert not plain or all(
    {r["id"]: r for r in rows}[i]["family"] in ("LDA", "GGA", "MGGA")
    for i in plain), plain
print("derived:", derived)
print(f"covered={len(covered)} plain-semilocal-uncovered={len(plain)}")
for k, v in stored.items():
    print(f"{k}: {v}")
print("OK")
