#!/usr/bin/env python3
"""Regenerate whole-catalog-inventory.json from pinned source + oracle ledgers.

Fresh enumeration (not a self-check): parses per-identity family/kind/flags
from pinned Libxc src/*.c info structs, joins energy/proof status from
oracle-primal-ledger.json, and joins host-operator readbacks (cam/nlc/hyb_exx
+ aux component ids/names) from oracle-composites.json.

Repro:
  cd /tmp/libxcsrc/libxc  # at pin 7d236789c2a4521270eeaa41d06e0d721ef56abd
  python3 whole-catalog-inventory.py \\
    --src /tmp/libxcsrc/libxc/src \\
    --ledger ~/.scratch/sympy-xc/assets/oracle-primal-ledger.json \\
    --composites ~/.scratch/sympy-xc/assets/oracle-composites.json \\
    --out whole-catalog-inventory.json
  python3 whole-catalog-smoke.py whole-catalog-inventory.json
"""
import argparse
import glob
import json
import re

ap = argparse.ArgumentParser()
ap.add_argument("--src", required=True)
ap.add_argument("--ledger", required=True)
ap.add_argument("--composites", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()

infos = {}
for f in sorted(glob.glob(a.src + "/*.c")):
    text = open(f).read()
    for m in re.finditer(
        r"const\s+xc_func_info_type\s+xc_func_info_(\w+)\s*=\s*\{(.*?)\n\};",
        text, re.S):
        body = m.group(2)
        fam = re.search(r"XC_FAMILY_(\w+)", body)
        kind = re.search(
            r"XC_(EXCHANGE_CORRELATION|EXCHANGE|CORRELATION|KINETIC)", body)
        flags = set(re.findall(r"XC_FLAGS_([A-Z0-9_]+)", body))
        infos[m.group(1)] = dict(
            fam=fam.group(1) if fam else "?",
            kind=kind.group(1) if kind else "?",
            flags=sorted(flags))
assert len(infos) == 709, len(infos)

led = json.load(open(a.ledger))["rows"]
comp = json.load(open(a.composites))
aux_by_fid = {}
for r in comp:
    aux_by_fid.setdefault(r["fid"], {})[r["spin"]] = {
        "cam": r["cam"], "nlc": r["nlc"], "hyb_exx": r["hyb_exx"],
        "aux_names": r["aux_names"],
        "aux": [[c["id"], c["name"], c["weight"]]
                for c in r["components"]],
        "mix_coef": r["mix_coef"]}

rows = []
for k, v in led.items():
    i = infos[k]
    fl = set(i["flags"])
    spins = v.get("spins", {}) or {}
    s1 = spins.get("1", {})
    s2 = spins.get("2", {})
    rt = s1.get("runtime", {}) or {}
    aux = aux_by_fid.get(v["fid"])
    rows.append(dict(
        id=v["fid"], name=k, aliases=v.get("aliases"),
        family=i["fam"], kind=i["kind"], cls=v.get("cls"),
        dim="3D" if "3D" in fl else ("2D" if "2D" in fl else
                                    ("1D" if "1D" in fl else "?")),
        dim_source_au=s1.get("dim_source"),
        dens_threshold=s1.get("dens_src"),
        needs_tau="NEEDS_TAU" in fl,
        needs_laplacian="NEEDS_LAPLACIAN" in fl,
        hyb_cam="HYB_CAM" in fl, hyb_camy="HYB_CAMY" in fl,
        vv10="VV10" in fl,
        nonlocal_kernel=("rvv10" if "VV10" in fl and "rvv10" in k
                         else ("vv10" if "VV10" in fl else None)),
        development="DEVELOPMENT" in fl,
        enforce_fhc="ENFORCE_FHC" in fl,
        energy_spin1=s1.get("zk"), energy_spin2=s2.get("zk"),
        source_only_clean=s1.get("source_only_clean"),
        proof_complete=s1.get("proof_complete"),
        runtime_cam=rt.get("cam"),
        runtime_hyb_exx=rt.get("hyb_exx"),
        aux_operators=aux,  # None for non-composite; cam/nlc/hyb_exx+comps
        module=s1.get("module"), base=v.get("base")))

rows.sort(key=lambda r: r["id"])
assert len(rows) == 709 and len({r["id"] for r in rows}) == 709


def L(pred):
    return [r["id"] for r in rows if pred(r)]


groups = {
    "semilocal_3d_energy": L(lambda r: r["cls"] == "primal"
                             and r["energy_spin1"] == "ok"
                             and r["family"] in ("LDA", "GGA", "MGGA")
                             and r["dim"] == "3D" and r["kind"] != "KINETIC"
                             and not r["needs_laplacian"] and not r["vv10"]),
    "laplacian_needs": L(lambda r: r["needs_laplacian"]),
    "global_hybrid": L(lambda r: r["family"] in (
        "HYB_LDA", "HYB_GGA", "HYB_MGGA")
        and not r["hyb_cam"] and not r["hyb_camy"]),
    "range_separated_erf_CAM": L(lambda r: r["hyb_cam"]),
    "yukawa_CAMY": L(lambda r: r["hyb_camy"]),
    "nonlocal_VV10": L(lambda r: r["vv10"]),
    "kinetic": L(lambda r: r["kind"] == "KINETIC"),
    "non3d": L(lambda r: r["dim"] != "3D"),
    "development": L(lambda r: r["development"]),
    "potential_only": L(lambda r:
                        r["energy_spin1"] == "NO_EXC_POTENTIAL_ONLY"),
    "spline_opaque_CASE21": [390],
    "enforce_fhc": L(lambda r: r["enforce_fhc"]),
    "composites_mix_only": L(lambda r: r["cls"] == "mix_only"),
}
inv = dict(meta=dict(
    libxc_pin="7d236789c2a4521270eeaa41d06e0d721ef56abd", runtime="7.1.2",
    n_identities=709, n_names=725, n_primal=555, n_mix_only=154,
    energy_spin_ok=1094, potential_only_spin_records=14,
    spline_opaque_spin_records=2,
    source="fresh parse of src/*.c info structs + oracle ledgers"),
    groups=groups, rows=rows)
json.dump(inv, open(a.out, "w"), indent=1)
print({k: len(vv) for k, vv in groups.items()})
print("RECONCILED 709/709")
