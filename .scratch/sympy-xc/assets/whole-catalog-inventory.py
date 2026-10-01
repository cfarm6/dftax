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
numdefs = {}  # XC_* name -> number, from #defines across src
for f in sorted(glob.glob(a.src + "/*.c") + glob.glob(a.src + "/*.h")):
    for m in re.finditer(r"#define\s+(XC_[A-Z0-9_]+)\s+(\d+)",
                         open(f).read()):
        numdefs.setdefault(m.group(1), int(m.group(2)))
for f in sorted(glob.glob(a.src + "/*.c")):
    text = open(f).read()
    incs = re.findall(r'#include\s+"(maple2c/[^"]+)"', text)
    expansions = set()
    for inc in incs:
        try:
            t2 = open(a.src + "/" + inc).read()
        except OSError:
            continue
        d = re.search(r"#define\s+MAPLE2C_FLAGS\s+(.*?)\n", t2)
        if d:
            expansions.add(d.group(1).strip())
    assert len(expansions) <= 1, (f, expansions)
    expansion = next(iter(expansions)) if expansions else None
    for m in re.finditer(
            r"const\s+xc_func_info_type\s+xc_func_info_(\w+)\s*=\s*\{(.*?)\n\};",
            text, re.S):
        body = m.group(2)
        fam = re.search(r"XC_FAMILY_(\w+)", body)
        kind = re.search(
            r"XC_(EXCHANGE_CORRELATION|EXCHANGE|CORRELATION|KINETIC)", body)
        flags = set(re.findall(r"XC_FLAGS_([A-Z0-9_]+)", body))
        numtok = body.split(",")[0].strip()
        src_id = numdefs.get(numtok)
        assert src_id is not None, (f, m.group(1), numtok)
        deriv = sorted(re.findall(r"XC_FLAGS_(I_HAVE_[A-Z]+|HAVE_[A-Z]+)",
                                  body))
        if "MAPLE2C_FLAGS" in body:
            assert expansion is not None, (f, m.group(1))
            # resolved availability: expand included generated macro.
            # This is the source-declared derivative availability, NOT a
            # MAXORDER=0 oracle claim: the pinned oracle build caps helper
            # differentiation at order 0 (defaults+energy only).
            deriv = sorted(set(deriv)
                           | set(re.findall(r"XC_FLAGS_(I_HAVE_[A-Z]+)",
                                            expansion)))
            maple = "MAPLE2C_FLAGS"
        else:
            maple = None
        infos[m.group(1)] = dict(
            src_id=src_id,
            fam=fam.group(1) if fam else "?",
            kind=kind.group(1) if kind else "?",
            flags=sorted(flags),
            raw_flags=(sorted("XC_FLAGS_" + f for f in flags) +
                       ([maple] if maple else [])),
            deriv_flags=deriv,
            maple_expansion=expansion,
            maple2c=bool(maple),
            def_file=f.split("/")[-1])
assert len(infos) == 709, len(infos)

# registration set equality: funcs_key.c names/ids == xc_funcs.h ids == ledger
key_pairs = re.findall(r'\{"([^"]+)",\s*(\d+)\}',
                       open(a.src + "/funcs_key.c").read())
key_ids = sorted({int(i) for _, i in key_pairs})
key_names = sorted({n for n, _ in key_pairs})
h_ids = sorted(set(numdefs.values()))
led = json.load(open(a.ledger))["rows"]
led_ids = sorted(v["fid"] for v in led.values())
src_ids = sorted(v["src_id"] for v in infos.values())
assert src_ids == led_ids == key_ids, (
    len(src_ids), len(led_ids), len(key_ids))
mismatch = [k for k, v in led.items()
            if infos[k]["src_id"] != v["fid"]]
assert not mismatch, mismatch
led_names = set()
for v in led.values():
    led_names.update(v.get("aliases", []))
assert sorted(led_names) == key_names, (
    len(led_names), len(key_names))

comp = json.load(open(a.composites))
aux_by_fid = {}
for r in comp:
    aux_by_fid.setdefault(r["fid"], {})[r["spin"]] = {
        "cam": r["cam"], "nlc": r["nlc"], "hyb_exx": r["hyb_exx"],
        "aux_names": r["aux_names"],
        "aux": [[c["id"], c["name"], c["weight"]]
                for c in r["components"]],
        "mix_coef": r["mix_coef"],
        "coef_note": r.get("coef_note"),
        "discrepancy": r.get("discrepancy", []),
        "components": [
            {"slot": c["slot"], "id": c["id"], "name": c["name"],
             "weight": c["weight"], "cmp": c["cmp"],
             "ext_effective": c["ext_effective"],
             "ext_standalone": c["ext_standalone"],
             "overridden": c.get("overridden"), "at_default": c.get("at_default"),
             "params": c.get("params"), "params_limit": c.get("params_limit")}
            for c in r["components"]]}
assert len(comp) == 308, len(comp)
from collections import Counter as _C
assert _C(r["spin"] for r in comp) == {1: 154, 2: 154}, _C(
    r["spin"] for r in comp)
mix_fids = sorted(v["fid"] for v in led.values() if v["cls"] == "mix_only")
assert sorted(aux_by_fid) == mix_fids, (
    len(aux_by_fid), len(mix_fids))
assert all(sorted(aux_by_fid[f]) == [1, 2] for f in aux_by_fid)
assert all(not aux_by_fid[f][s]["discrepancy"]
           for f in aux_by_fid for s in (1, 2))
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
        operator_class=(
            "finite-T free energy" if v["fid"] in (259, 318, 577)
            else ("multicomponent electron-proton" if v["fid"] in
                  (328, 329, 330, 331) else None)),
        nonlocal_kernel=(
            "VV10-flagged/rVV10-intended-TBD" if v["fid"] == 652
            else ("rvv10" if v["fid"] in (292, 703)
                  or ("VV10" in fl and "rvv10" in k
                      and v["fid"] not in (652,))
                  else ("vv10" if "VV10" in fl else None))),
        development="DEVELOPMENT" in fl,
        enforce_fhc="ENFORCE_FHC" in fl,
        raw_flags=i.get("raw_flags"), deriv_flags=i.get("deriv_flags"),
        maple2c=i.get("maple2c"),
        energy_spin1=s1.get("zk"), energy_spin2=s2.get("zk"),
        source_only_clean=s1.get("source_only_clean"),
        proof_complete=s1.get("proof_complete"),
        runtime_cam=rt.get("cam"),
        runtime_hyb_exx=rt.get("hyb_exx"),
        aux_operators=aux,  # None for non-composite; cam/nlc/hyb_exx+comps
        # + coef_note/discrepancy/per-component cmp+params provenance
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
    "thermal_finite_T": [259, 318, 577],
    "multicomponent_epc": [328, 329, 330, 331],
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
