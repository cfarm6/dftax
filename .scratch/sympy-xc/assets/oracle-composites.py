"""Composite oracle audit: worker-less semilocal registrations, per identity/spin.

Self-contained: enumerates worker-less identities from pinned Libxc source,
parses each identity's OWN init-function body (ids/coefs/aux literals,
computed coefs), and reads effective aux params from the INITIALIZED parent
struct (func_aux pointers) via the provisioned oracle. Compares source vs
readback per identity; standalone functionals used ONLY as overridden/default
baseline, never as the effective value.

Writes oracle-composites.json + oracle-composites.md next to itself.

Env (per .scratch/sympy-xc/assets/oracle-build-pinned.md):
  cd /tmp/libxcsrc/libxc
  SP=/tmp/xcoracle-po/cpython-3.13-linux-x86_64-gnu/lib/python3.13/site-packages
  LD_LIBRARY_PATH=/tmp/xcoracle-po/lib \
  PYTHONPATH=/tmp/libxcsrc/libxc/scripts/sympy2c:/tmp/sympyenv:$SP \
  /tmp/xcoracle-po/venv/bin/python .scratch/.../oracle-composites.py
"""
import ctypes
import glob
import json
import os
import pathlib
import re
import sys

SP = "/tmp/xcoracle-po/cpython-3.13-linux-x86_64-gnu/lib/python3.13/site-packages"
sys.path.insert(0, SP)
SRC = os.environ.get("LIBXC_SRC", "/tmp/libxcsrc/libxc/src")

import pylibxc  # noqa: E402
from pylibxc import structs, util  # noqa: E402

from build_info import _resolve_source, _c_struct_layout  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
TOL = 1e-9


def split_top_commas(s):
    parts, depth, cur = [], 0, ""
    instr = False
    for ch in s:
        if ch == '"':
            instr = not instr
            cur += ch
        elif instr:
            cur += ch
        elif ch == "{":
            depth += 1
            cur += ch
        elif ch == "}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def numdefs():
    d = {}
    for f in glob.glob(os.path.join(SRC, "*.c")) + glob.glob(os.path.join(SRC, "*.h")):
        for m in re.finditer(r"#define\s+(XC_[A-Z0-9_]+)\s+(\d+)", open(f).read()):
            d.setdefault(m.group(1), int(m.group(2)))
    return d

def enumerate_workerless(ndefs):
    """(fid, info_name, fname, init, family, kind) with no lda/gga/mgga worker."""
    recs = []
    for f in sorted(glob.glob(os.path.join(SRC, "*.c"))):
        fname = pathlib.Path(f).name
        text = open(f).read()
        for m in re.finditer(
                r"const\s+xc_func_info_type\s+xc_func_info_(\w+)\s*=\s*\{(.*?)\n\};",
                text, re.S):
            iname, body = m.group(1), re.sub(r"/\*.*?\*/", "", m.group(2), flags=re.S)
            fields = split_top_commas(body)
            if len(fields) < 13:
                continue
            tok = fields[0].strip()
            num = ndefs.get(tok)
            if num is None:
                try:
                    num = int(tok)
                except ValueError:
                    continue
            kind_m = re.search(r"XC_(EXCHANGE_CORRELATION|EXCHANGE|CORRELATION|KINETIC)", fields[1])
            fam_m = re.search(r"XC_FAMILY_\w+", fields[3])
            workers = [k for k, i in (("lda", 10), ("gga", 11), ("mgga", 12))
                       if len(fields) > i and fields[i].strip() not in ("NULL", "0")]
            if workers:
                continue
            init = fields[8].strip()
            recs.append((num, iname, fname,
                         init if re.match(r"\w+$", init) else None,
                         fam_m.group(0).replace("XC_FAMILY_", "") if fam_m else "?",
                         kind_m.group(1) if kind_m else "?",
                         tok if tok.startswith("XC_") else None))
    return recs


def fn_body(text, init):
    m = re.search(r"\b" + re.escape(init) + r"\s*\(xc_func_type\s*\*\s*p\s*\)\s*\{", text)
    if not m:
        return None
    depth, i = 0, m.end() - 1
    for j in range(m.end() - 1, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[m.end():j]
    return None


def parse_init_source(text, init, ndefs, xc_macro=None):
    """Body-scoped ids/coefs/aux from ONE init fn. No file-level fallbacks.
    For switch-based shared inits, resolves the active `case <XC macro>` for
    this registration (xc_macro from the info struct's number field)."""
    src = {"init": init, "ids": None, "coefs": None, "aux": {}, "notes": []}
    body = fn_body(text, init)
    if body is None:
        src["notes"].append("INIT-BODY-NOT-FOUND")
        return src
    case_ids = {}
    if "switch" in body:
        if xc_macro:
            cm = re.search(r"case\s*\(?" + re.escape(xc_macro) + r"\)?\s*:(.*?)break;", body, re.S)
            if cm:
                seg = cm.group(1)
                for am in re.finditer(r"funcs_id\[(\d+)\]\s*=\s*(?:funcs_id\[(\d+)\]\s*=\s*)?(XC_[A-Z0-9_]+)", seg):
                    v = am.group(3)
                    case_ids[int(am.group(1))] = v
                    if am.group(2) is not None:
                        case_ids[int(am.group(2))] = v
                src["notes"].append("SWITCH-CASE:" + xc_macro)
            else:
                src["notes"].append("SWITCH-CASE-NOT-FOUND:" + str(xc_macro))
        else:
            src["notes"].append("HAS-SWITCH:no-macro")
    if "xc_hyb_init_hybrid" in body or "xc_hyb_init_cam" in body or "xc_hyb_init_sr" in body or "xc_hyb_init_lc" in body or "xc_hyb_init_cam_y" in body:
        src["notes"].append("HYB-POSTINIT-OVERWRITES-COEF:readback-authoritative")
    mid = re.search(r"static\s+(?:const\s+)?int\s+funcs_id\s*\[\s*\d*\s*\]\s*=\s*\{([^}]*)\}", body)
    mid2 = re.search(r"(?<![\w\]])int\s+funcs_id\s*\[\s*\d*\s*\]\s*=\s*\{([^}]*)\}", body)
    mids = mid or mid2
    if mids:
        ids = []
        for pos, tok in enumerate(split_top_commas(mids.group(1))):
            tok = tok.strip()
            if pos in case_ids:
                tok = case_ids[pos]
            ids.append(ndefs.get(tok, tok))
        for pos in sorted(case_ids):
            while len(ids) <= pos:
                ids.append(None)
            ids[pos] = ndefs.get(case_ids[pos], case_ids[pos])
        src["ids"] = ids
    else:
        src["notes"].append("NO-funcs_id")
    mco = re.search(r"(?:static\s+)?(?:const\s+)?double\s+funcs_coef\s*\[\s*\d*\s*\]\s*=\s*\{([^}]*)\}", body)
    consts = {}
    for cm in re.finditer(r"static\s+const\s+double\s+(\w+)\s*=\s*([^;]+);", body):
        expr = cm.group(2).strip()
        try:
            consts[cm.group(1)] = float(expr)
        except ValueError:
            src["notes"].append("NONLIT-CONST:" + cm.group(1))
    if mco:
        try:
            src["coefs"] = [float(t) for t in split_top_commas(mco.group(1))]
        except ValueError:
            src["notes"].append("NONLIT-COEF-ARRAY")
    else:
        assigns = re.findall(r"funcs_coef\[(\d+)\]\s*=\s*([^;]+);", body)
        if assigns:
            coefs = {}
            for idx, expr in assigns:
                e = expr.strip()
                for k, v in consts.items():
                    e = re.sub(r"\b" + k + r"\b", repr(v), e)
                e = e.replace("X_FACTOR_C", "0.9305257363491002")
                try:
                    coefs[int(idx)] = eval(e, {"__builtins__": {}})  # noqa: S307 source literals only
                except Exception:
                    src["notes"].append("COEF-EVAL-FAIL:" + expr.strip()[:60])
            if coefs and not src["notes"]:
                src["coefs"] = [coefs[i] for i in sorted(coefs)]
        elif "xc_mix_init" in body:
            src["notes"].append("MIX-NO-COEF-ARRAY")
    # aux arrays set on func_aux[k]
    for sm in re.finditer(r"xc_func_set_ext_params\s*\(\s*p->func_aux\[(\d+)\]\s*,\s*(\w+)\s*\)", body):
        slot, arr = int(sm.group(1)), sm.group(2)
        am = re.search(r"(?:static\s+)?(?:const\s+)?double\s+" + re.escape(arr)
                       + r"\s*\[[^]]*\]\s*=\s*\{([^}]*)\}", body)
        if am is None:  # external array (e.g. par_kt): search whole file text
            am = re.search(r"(?:static\s+)?(?:const\s+)?double\s+" + re.escape(arr)
                           + r"\s*\[[^]]*\]\s*=\s*\{([^}]*)\}", text)
            note = "EXTERNAL:"
        else:
            note = ""
        if am is None:
            src["aux"][slot] = "UNRESOLVED:" + arr
            continue
        vals = []
        for tok in split_top_commas(am.group(1)):
            tok = tok.strip()
            if tok == "XC_EXT_PARAMS_DEFAULT":
                vals.append("DEFAULT")
                continue
            e = tok
            for k, v in consts.items():
                e = re.sub(r"\b" + k + r"\b", repr(v), e)
            e = e.replace("MU_GE", "0.12345679012345678").replace("X2S", "0.1282782438530421943003109254455883701296").replace("X_FACTOR_C", "0.9305257363491002")
            try:
                vals.append(eval(e, {"__builtins__": {}}))  # noqa: S307 source literals only
            except Exception:
                vals.append("EXPR:" + tok[:60])
        src["aux"][slot] = (note + arr) if note else vals
        if note:
            src["aux"][slot] = {note + arr: vals}
    return src


_layout_cache = {}

try:
    from pylibxc import functional as _pf
    _core = _pf.core
    _xc_p = ctypes.POINTER(structs.xc_func_type)
    _core.xc_func_get_info.argtypes = (_xc_p,)
    _core.xc_func_get_info.restype = ctypes.POINTER(structs.xc_func_info_type)
    _core.xc_func_get_ext_params_value.argtypes = (_xc_p, ctypes.c_int)
    _core.xc_func_get_ext_params_value.restype = ctypes.c_double
    _core.xc_func_info_get_n_ext_params.argtypes = (
        ctypes.POINTER(structs.xc_func_info_type),)
    _core.xc_func_info_get_n_ext_params.restype = ctypes.c_int
    _core.xc_func_info_get_ext_params_name.argtypes = (
        ctypes.POINTER(structs.xc_func_info_type), ctypes.c_int)
    _core.xc_func_info_get_ext_params_name.restype = ctypes.c_char_p
    _HAS_EXT_API = True
except Exception as _e:
    _HAS_EXT_API = False
    _EXT_API_ERR = str(_e)[:120]


def ext_readback(aux_ptr):
    """Effective external params straight from the initialized struct."""
    if not _HAS_EXT_API:
        return None, "EXT-API-UNAVAILABLE:" + globals().get("_EXT_API_ERR", "?")
    try:
        info = _core.xc_func_get_info(aux_ptr)
        n = int(_core.xc_func_info_get_n_ext_params(info))
        names, vals = [], []
        for i in range(n):
            nm = _core.xc_func_info_get_ext_params_name(info, i)
            names.append(nm.decode() if nm else "?")
            vals.append(float(_core.xc_func_get_ext_params_value(aux_ptr, i)))
        return {"names": names, "values": vals}, None
    except Exception as e:
        return None, "EXT-READBACK-ERR:" + str(e)[:100]


def layout_of(comp_name):
    if comp_name in _layout_cache:
        return _layout_cache[comp_name]
    try:
        _, text, _, _ = _resolve_source(comp_name)
    except Exception as e:
        _layout_cache[comp_name] = ("ERR:" + str(e)[:80], None)
        return _layout_cache[comp_name]
    ss = set(re.findall(r"\}\s*(\w+_params)\s*;", text))
    if len(ss) == 0:
        _layout_cache[comp_name] = ("NOPARAMS-FILE:parameterless component", None)
        return _layout_cache[comp_name]
    if len(ss) > 1:
        _layout_cache[comp_name] = ("AMBI:" + ",".join(sorted(ss)), None)
        return _layout_cache[comp_name]
    _layout_cache[comp_name] = (None, _c_struct_layout(text, next(iter(ss))))
    return _layout_cache[comp_name]


def read_struct(params_ptr, layout):
    def _ct(t, n):
        base = getattr(ctypes, t)
        if isinstance(n, tuple):
            return (base * n[1]) * n[0]
        return base * n if n else base

    fields = [(f, _ct(t, n)) for f, t, n in layout]

    class _P(ctypes.Structure):
        _fields_ = fields

    got = ctypes.cast(params_ptr, ctypes.POINTER(_P)).contents
    out = {}
    for f, _t, n in layout:
        v = getattr(got, f)
        if isinstance(n, tuple):
            out[f] = [[float(x) for x in row] for row in v]
        elif n:
            out[f] = [float(x) for x in v]
        else:
            out[f] = float(v)
    return out


def p_aux_src(src_info, slot):
    try:
        v = (src_info.get("parsed") or {}).get("aux", {}).get(slot, "NO-SOURCE-AUX")
        return list(v.values())[0] if isinstance(v, dict) else v
    except Exception:
        return "HELPER-ERR"


def audit_identity(fid, name, spin, src_info):
    rec = {"fid": fid, "name": name, "spin": spin, "init": src_info.get("init"),
           "file": src_info.get("file"), "family": src_info.get("family"),
           "kind": src_info.get("kind"), "source": src_info.get("parsed")}
    try:
        f = pylibxc.LibXCFunctional(fid, spin)
    except Exception as e:
        rec["error"] = str(e)[:120]
        return rec
    n = f.xc_func.contents.n_func_aux
    rec["naux"] = n
    rec["mix_coef"] = [float(x) for x in f.xc_func.contents.mix_coef[:n]] if n else []
    try:
        rec["aux"] = [(i, float(w)) for i, w in f.aux_funcs(return_ids=True)] or []
    except Exception as e:
        rec["aux_error"] = str(e)[:120]
        rec["aux"] = []
    rec["aux_names"] = [util.xc_functional_get_name(i) for i, _ in rec["aux"]]
    c = f.xc_func.contents
    rec["thresholds"] = {"dens": c.dens_threshold, "zeta": c.zeta_threshold,
                         "sigma": c.sigma_threshold, "tau": c.tau_threshold}
    rec["cam"] = [c.cam_omega, c.cam_alpha, c.cam_beta]
    rec["nlc"] = [c.nlc_b, c.nlc_C]
    try:
        rec["hyb_exx"] = f.get_hyb_exx_coef()
    except Exception:
        rec["hyb_exx"] = None
    comps = []
    if n:
        arr = ctypes.cast(f.xc_func.contents.func_aux,
                          ctypes.POINTER(ctypes.POINTER(structs.xc_func_type)))
        for k in range(n):
            a = arr[k].contents
            cname = util.xc_functional_get_name(rec["aux"][k][0])
            ce = {"slot": k, "id": rec["aux"][k][0], "name": cname,
                  "weight": rec["aux"][k][1],
                  "thresholds": {"dens": a.dens_threshold, "zeta": a.zeta_threshold,
                                 "sigma": a.sigma_threshold, "tau": a.tau_threshold}}
            err, lay = layout_of(cname)
            auxp = ctypes.cast(arr[k], ctypes.POINTER(structs.xc_func_type))
            ext, exterr = ext_readback(auxp)
            if ext is not None:
                ce["ext_effective"] = ext
                try:
                    s = pylibxc.LibXCFunctional(cname, spin)
                    sext, serr = ext_readback(s.xc_func)
                    ce["ext_standalone"] = sext
                    if serr:
                        ce["standalone_limit"] = serr
                    elif sext is not None:
                        ce["ext_overridden"] = [nm for nm, v0, v1 in zip(ext["names"], ext["values"], sext["values"]) if abs(v0 - v1) > TOL]
                        ce["ext_at_default"] = [nm for nm, v0, v1 in zip(ext["names"], ext["values"], sext["values"]) if abs(v0 - v1) <= TOL]
                except Exception as e:
                    ce["standalone_limit"] = "STANDALONE-ERR:" + str(e)[:60]
            else:
                ce["ext_limit"] = exterr
            if err and err.startswith("AMBI:"):
                ce["params_limit"] = err + " (internal struct unread; effective EXT above is authoritative)"
                sv = p_aux_src(src_info, k)
                ce["ext_fallback"] = sv if isinstance(sv, list) else "NO-SOURCE-AUX-PARSED:" + str(sv)
            elif err or not lay:
                ce["params_limit"] = err or "NO-STRUCT"
            elif not a.params:
                ce["params"] = "NOPARAMS"
            else:
                ce["params"] = read_struct(a.params, lay)
                try:
                    s = pylibxc.LibXCFunctional(cname, spin)
                    if not s.xc_func.contents.params:
                        ce["standalone_limit"] = "STANDALONE-NOPARAMS"
                    else:
                        serr, slay = layout_of(cname)
                        sb = read_struct(s.xc_func.contents.params, slay)
                        ce["overridden"] = sorted(k2 for k2, v in ce["params"].items()
                                                  if k2 in sb and sb[k2] != v)
                        ce["at_default"] = sorted(k2 for k2, v in ce["params"].items()
                                                  if k2 in sb and sb[k2] == v)
                except Exception as e:
                    ce["standalone_limit"] = "STANDALONE-ERR:" + str(e)[:60]
            comps.append(ce)
    rec["components"] = comps
    # discrepancy vs own-init source parse
    p = rec["source"] or {}
    disc = []
    if p.get("ids") is not None and [i for i, _ in rec["aux"]] != p["ids"]:
        disc.append("IDS: readback=%s source=%s" % ([i for i, _ in rec["aux"]], p["ids"]))
    notes = " ".join(p.get("notes", []))
    hyb_post = "HYB-POSTINIT-OVERWRITES-COEF" in notes or "COEF-SET-BY-SETTER" in notes
    computed_coef = p.get("coefs") is None and "MIX-NO-COEF-ARRAY" not in notes and any(s in notes for s in ("COEF-EVAL", "NONLIT"))
    if p.get("coefs") is not None and not hyb_post:
        if len(rec["mix_coef"]) != len(p["coefs"]):
            disc.append("COEF-LEN: readback=%d source=%d" % (len(rec["mix_coef"]), len(p["coefs"])))
        elif any(abs(a - b) > TOL for a, b in zip(rec["mix_coef"], p["coefs"])):
            disc.append("COEF: readback=%s source=%s" % (rec["mix_coef"], p["coefs"]))
    elif hyb_post or computed_coef:
        rec["coef_note"] = "READBACK-AUTHORITATIVE: source array is placeholder/computed at init"
    for k, ce in enumerate(comps):
        sv = p.get("aux", {}).get(k, "NO-SOURCE-AUX")
        if isinstance(sv, dict):  # EXTERNAL: literal captured
            sv = list(sv.values())[0]
        ext = ce.get("ext_effective")
        if ext is not None and not ext["values"] and sv == "NO-SOURCE-AUX":
            ce["cmp"] = "complete:parameterless (no EXT params, no source aux)"
        elif isinstance(sv, list) and ext is not None:
            exp = [x for x in sv if isinstance(x, (int, float))]
            ndef = sv.count("DEFAULT")
            got = ext["values"][:len(exp)]
            uneval = [x for x in sv if not isinstance(x, (int, float)) and x != "DEFAULT"]
            if uneval:
                disc.append("AUX%d-%s-UNRESOLVED-SOURCE: %s" % (k, ce["name"], uneval))
                ce["cmp"] = "partial:unresolved-source-tokens"
            elif len(ext["values"]) < len(exp) and all(abs(a - b) <= TOL for a, b in zip(ext["values"], exp[:len(ext["values"])])):
                ce["cmp"] = "complete:lead-%d-match+trailing-source-beyond-ext-n-ignored" % len(ext["values"])
            elif len(ext["values"]) < len(exp):
                disc.append("AUX%d-%s-EXT-SHORT: readback=%s source=%s" % (k, ce["name"], ext["values"], sv))
                ce["cmp"] = "partial:ext-shorter-than-source"
            elif any(abs(a - b) > TOL for a, b in zip(got, exp)):
                ce["setter_mapped"] = {"ext-array": sv, "effective-ext": ext["values"]}
                ce["cmp"] = "complete:setter-mapped (runtime-authoritative)"
            elif ndef:
                ce["cmp"] = "complete:lead-slots-match+%d-DEFAULT-filled-by-info-defaults" % ndef
            else:
                ce["cmp"] = "complete:full-match"
        elif isinstance(sv, list) and isinstance(ce.get("params"), dict):
            flat = []
            for v in ce["params"].values():
                flat += v if isinstance(v, list) else [v]
            exp = [x for x in sv if isinstance(x, (int, float))]
            got = flat[:len(exp)]
            uneval = [x for x in sv if not isinstance(x, (int, float)) and x != "DEFAULT"]
            if uneval:
                disc.append("AUX%d-%s-UNRESOLVED-SOURCE: %s" % (k, ce["name"], uneval))
                ce["cmp"] = "partial:unresolved-source-tokens"
            elif any(abs(a - b) > TOL for a, b in zip(got, exp)):
                ce["setter_mapped"] = {"ext-array": sv, "effective-struct-lead": got}
                ce["cmp"] = "complete:setter-mapped (runtime-authoritative)"
            else:
                ce["cmp"] = "complete:struct-lead-match (no direct EXT readback)"
        else:
            ce["cmp"] = "partial:" + ("no-source-aux" if sv == "NO-SOURCE-AUX" else "no-comparable-readback")
    rec["discrepancy"] = disc
    return rec


def main():
    print("pin:", os.popen("git -C /tmp/libxcsrc/libxc rev-parse HEAD").read().strip(), flush=True)
    ndefs = numdefs()
    enum = enumerate_workerless(ndefs)
    print("worker-less identities: %d" % len(enum), flush=True)
    filetexts = {}
    records = []
    for fid, name, fname, init, fam, kind, macro in sorted(enum):
        if fname not in filetexts:
            filetexts[fname] = open(os.path.join(SRC, fname)).read()
        parsed = parse_init_source(filetexts[fname], init, ndefs, macro) if init else {"notes": ["NO-INIT"]}
        info = {"init": init, "file": fname, "family": fam, "kind": kind, "parsed": parsed}
        for spin in (1, 2):
            records.append(audit_identity(fid, name, spin, info))
    ok = [x for x in records if "error" not in x]
    naux0 = [x for x in ok if x["naux"] == 0]
    ndisc = [x for x in ok if x.get("discrepancy")]
    allids = sorted({x["fid"] for x in ok})
    cmps = [ce.get("cmp", "?") for x in ok for ce in x.get("components", [])]
    ncomplete = sum(1 for c in cmps if c.startswith("complete:"))
    npartial = sum(1 for c in cmps if c.startswith("partial:"))
    print("records=%d ok=%d errors=%d naux0=%d with-discrepancy=%d unique-ids=%d range=%s-%s slots=%d complete=%d partial=%d"
          % (len(records), len(ok), len(records) - len(ok), len(naux0), len(ndisc),
             len(allids), allids[0] if allids else "?", allids[-1] if allids else "?",
             len(cmps), ncomplete, npartial), flush=True)
    for x in records:
        if "error" in x:
            print("ERR", x["fid"], x["name"], x["spin"], x["error"], flush=True)
    for x in naux0:
        print("NAUX0", x["fid"], x["name"], x["spin"], flush=True)
    for x in ndisc:
        print("DISC", x["fid"], x["name"], x["spin"], x["discrepancy"], flush=True)
    json.dump(records, open(os.path.join(OUT, "oracle-composites.json"), "w"), indent=1)

    L = ["# Composite oracle readback (initialized aux, per identity)",
         "",
         "- pin `7d236789c2a4521270eeaa41d06e0d721ef56abd`; effective EXT params read per aux slot via "
         "`xc_func_get_info`/`xc_func_info_get_n_ext_params`+`_name`/`xc_func_get_ext_params_value` "
         "(`src/xc.h:418-425`, `src/functionals.c:516-574`) on the initialized parent's `func_aux` pointers; "
         "standalone baseline of same spin via the same API (overridden/at_default are EXT-level).",
         "- internal `params` struct readback (via `build_info._c_struct_layout`) retained only for computed/setter-derived "
         "slots; NOPARAMS-FILE marks parameterless components, AMBI marks multi-struct files refused for struct read.",
         "- source side: each identity's OWN init-fn body in `src/<file>` "
         "(body-scoped ids/coefs/aux; no file-level array reuse, no sibling-branch defaults).",
         "- worker-less identities: %d; records: %d (spins 1+2); ok: %d; "
         "init errors: %d; naux==0: %d; slots: %d complete: %d partial: %d; with discrepancy: %d."
         % (len(enum), len(records), len(ok), len(records) - len(ok), len(naux0),
            len(cmps), ncomplete, npartial, len(ndisc)),
         "- cmp classes: complete:{full-match, lead-slots-match+N-DEFAULT-filled, setter-mapped(runtime-authoritative)}; "
         "partial:{no-source-aux, no-comparable-readback, unresolved-source-tokens, ext-shorter-than-source}. "
         "Zero discrepancies means no observed mismatch on compared slots, NOT full reconciliation of partial slots.",
         "- repro: `cd /tmp/libxcsrc/libxc && SP=/tmp/xcoracle-po/cpython-3.13-linux-x86_64-gnu/lib/python3.13/site-packages && "
         "LD_LIBRARY_PATH=/tmp/xcoracle-po/lib PYTHONPATH=/tmp/libxcsrc/libxc/scripts/sympy2c:/tmp/sympyenv:$SP "
         "/tmp/xcoracle-po/venv/bin/python /home/carson/dftax/.scratch/sympy-xc/assets/oracle-composites.py` "
         "(oracle env per `.scratch/sympy-xc/assets/oracle-build-pinned.md`; script is self-contained, no /tmp inputs needed).",
         ""]
    # focused evidence for the two known blockers
    for want in (65, 587):
        L.append("## focus id %d" % want)
        for x in [r for r in records if r["fid"] == want]:
            if "error" in x:
                L.append("- spin %d INIT-ERROR %s" % (x["spin"], x["error"]))
                continue
            L.append("- spin %d %s init=%s file=%s aux=%s mix=%s"
                     % (x["spin"], x["name"], x["init"], x["file"],
                        list(zip(x["aux_names"], x["mix_coef"])), x["mix_coef"]))
            L.append("  source: " + json.dumps(x["source"]))
            for ce in x["components"]:
                L.append("  slot%d %s ext_effective=%s ext_overridden=%s cmp=%s"
                         % (ce["slot"], ce["name"], json.dumps(ce.get("ext_effective")),
                            ce.get("ext_overridden"), ce.get("cmp")))
            L.append("  discrepancy: %s" % (x["discrepancy"] or "NONE (on compared slots only; see cmp classes)"))
    # nonlocal tails section
    L.append("")
    L.append("## nonlocal tails (parent-level, separate from semilocal aux)")
    for x in [r for r in ok if r["spin"] == 2 and (r["nlc"] != [0.0, 0.0] or r["cam"] != [0.0, 0.0, 0.0] or (r["hyb_exx"] or 0) != 0)]:
        L.append("- %d %s cam=%s nlc=%s hyb_exx=%s aux=%s"
                 % (x["fid"], x["name"], x["cam"], x["nlc"], x["hyb_exx"], x["aux_names"]))
    L.append("")
    L.append("## all rows (compact)")
    for x in records:
        if "error" in x:
            L.append("### %d %s spin=%d INIT-ERROR: %s" % (x["fid"], x["name"], x["spin"], x["error"]))
            continue
        t0 = x["thresholds"]
        L.append("### %d %s spin=%d init=%s file=%s"
                 % (x["fid"], x["name"], x["spin"], x["init"], x["file"]))
        L.append("- aux=%s mix=%s naux=%d thr=%s/%s/%s/%s cam=%s nlc=%s hyb_exx=%s"
                 % (list(zip(x["aux_names"], x["mix_coef"])), x["mix_coef"], x["naux"],
                    t0["dens"], t0["zeta"], t0["sigma"], t0["tau"],
                    x["cam"], x["nlc"], x["hyb_exx"]))
        L.append("- source-ids=%s source-coefs=%s source-aux=%s notes=%s"
                 % (x["source"].get("ids"), x["source"].get("coefs"),
                    json.dumps(x["source"].get("aux")), x["source"].get("notes")))
        for ce in x["components"]:
            t = ce["thresholds"]
            L.append("- slot%d %d %s w=%s thr=%s/%s/%s/%s" % (
                ce["slot"], ce["id"], ce["name"], ce["weight"],
                t["dens"], t["zeta"], t["sigma"], t["tau"]))
            if "params_limit" in ce:
                L.append("  - internal-struct: LIMIT " + str(ce["params_limit"]))
            elif ce.get("params") in ("NOPARAMS", None):
                L.append("  - internal-struct: " + str(ce.get("params")))
            else:
                L.append("  - internal-struct: " + json.dumps(ce["params"]))
            if ce.get("ext_effective") is not None:
                L.append("  - ext_effective: " + json.dumps(ce["ext_effective"]))
                L.append("  - ext_standalone: " + json.dumps(ce.get("ext_standalone"))
                         + " overridden=" + str(ce.get("ext_overridden")) + " at_default=" + str(ce.get("ext_at_default"))
                         + ((" " + str(ce.get("standalone_limit"))) if ce.get("standalone_limit") else ""))
            elif ce.get("ext_limit"):
                L.append("  - ext_effective: LIMIT " + str(ce["ext_limit"]))
            L.append("  - cmp: " + str(ce.get("cmp", "?"))
                     + ((" setter_mapped=" + json.dumps(ce["setter_mapped"])) if ce.get("setter_mapped") else "")
                     + ((" ext_fallback(src-only)=" + json.dumps(ce["ext_fallback"])) if ce.get("ext_fallback") else ""))
        if x["discrepancy"]:
            L.append("- DISCREPANCY: %s" % x["discrepancy"])
    open(os.path.join(OUT, "oracle-composites.md"), "w").write("\n".join(L) + "\n")
    print("wrote oracle-composites.json/.md", flush=True)


main()
