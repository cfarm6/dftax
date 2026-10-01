#!/usr/bin/env python3
"""Primal/default audit: full numeric-binding proof per candidate.

Provenance layers (never conflated):
  L1 source-only: _read_parameters + source-parsed CAM (ext setter +
    p->cam_* direct; NO pylibxc) + _C_CONSTANTS + dens/zeta thresholds.
  L1b own-CAM: _read_cam_defaults fallback (runtime xc_hyb_cam_coef
    authority for source-silent hybrids).
  L2 resolver: maple_reference.resolved_params (may use runtime CAM) +
    computed_param_keys overrides.
  L3 initialized: _built_parameters readback, last-resort loose only.
Proof: threshold_subs assembled with eval_reference precedence; L1-clean
proof via actual _dag_xreplace(eps, L1 bindings) BEFORE L1b/L2/L3; residual
= ALL Symbol leaves minus kernel ingredient arg_syms. Exact fills recorded.
TIMEOUT/ERR rows are proof-incomplete prerequisites, never coverage.
"""
import sys, os, re, glob, json, signal, argparse, collections

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIBXC = '/tmp/libxcsrc/libxc'
_SRC = os.path.join(_LIBXC, 'src')
SP = ('/tmp/xcoracle-po/cpython-3.13-linux-x86_64-gnu'
      '/lib/python3.13/site-packages')
for _p in (SP, os.path.join(_LIBXC, 'scripts/sympy2c'),
           os.path.join(_LIBXC, 'python'), '/tmp/sympyenv'):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.path.remove(SP)
sys.path.insert(0, SP)
os.chdir(_LIBXC)

import sympy as sp  # noqa: E402
import pylibxc  # noqa: E402
import libxc_codegen as L  # noqa: E402
from build_info import (_import_functional, _built_parameters,  # noqa: E402
                        _resolve_source, _read_parameters, _read_cam_defaults,
                        _read_dens_threshold, _C_CONSTANTS,
                        _CAM_SETTERS, _eval_param_value, _read_c_array)
from maple_reference import (resolved_params, computed_param_keys,  # noqa: E402
                             _resolve, _find_mpl)
from outputs import _kernel_outputs  # noqa: E402
from dag import _dag_nodes, _dag_xreplace, set_uncapped_ensure_order  # noqa: E402
from sympy2c import dens_threshold as _DENS_SYM, zeta_threshold as _ZETA_SYM  # noqa: E402
from sympy2c import cam_omega as _CAM_O, cam_alpha as _CAM_A, cam_beta as _CAM_B  # noqa: E402


class TO(Exception):
    pass


def _handler(s, f):
    raise TO()


signal.signal(signal.SIGALRM, _handler)
_SYM_OF = {"omega": _CAM_O, "alpha": _CAM_A, "beta": _CAM_B}


def cam_source_only(name):
    """{cam_symbol: value} from C source alone; {} if source is silent
    (hybrids via xc_hyb_init_cam need the runtime fallback)."""
    try:
        _, text, _, _ = _resolve_source(name)
    except Exception:
        return {}
    vals = {}
    if text:
        anchor = re.search(r"xc_func_info_" + re.escape(name) + r"\b", text)
        tail = text[anchor.start():] if anchor else text
        block = re.search(
            r"\{\s*\w+\s*,\s*\w+\s*,\s*\w+\s*,\s*(\w+)\s*,"
            r"\s*set_ext_params(?:_cpy)?_(\w+)", tail)
        if block:
            body = _read_c_array(text, block.group(1))
            setter = block.group(2)
            numbers = ([_eval_param_value(s) for s in body.split(",")]
                       if body is not None else [])
            numbers = [v for v in numbers if v is not None]
            for suffix, idx_map, fixed in _CAM_SETTERS:
                if setter == suffix:
                    for slot, idx in idx_map.items():
                        if len(numbers) >= -idx:
                            vals[slot] = numbers[idx]
                    vals.update(fixed)
                    break
        for slot in ("omega", "alpha", "beta"):
            if slot in vals:
                continue
            m = re.search(r"p->cam_" + slot + r"\s*=\s*([-+0-9][0-9.eE+\-]*)\s*;",
                          text)
            if m:
                v = _eval_param_value(m.group(1))
                if v is not None:
                    vals[slot] = v
    return {_SYM_OF[k]: v for k, v in vals.items()}


def runtime_thresholds(name, spin, fid=None):
    try:
        f = pylibxc.LibXCFunctional(fid if fid is not None else name, spin)
        c = f.xc_func.contents
        cam = [float(c.cam_omega), float(c.cam_alpha), float(c.cam_beta)]
        try:
            hx = float(f.get_hyb_exx_coef())
        except Exception:
            hx = None
        return {"dens": float(c.dens_threshold), "zeta": float(c.zeta_threshold),
                "sigma": float(c.sigma_threshold), "tau": float(c.tau_threshold),
                "cam": cam, "hyb_exx": hx}
    except Exception as e:
        return {"error": str(e)[:120]}


def _spline_table_keys(name, spin):
    # CASE21 spline state lives in initialized built params (mpmath_impls.py:
    # 273-344 rebuilds xbspline/cbspline from k/Nsp/knots/cx/cc). Detect via
    # built-params keys only -- never build numeric callbacks here.
    try:
        bp = dict(_built_parameters(name, spin))
    except Exception:
        return None  # unreadable: caller reports built_err, not "no table"
    if {"params_a_k", "params_a_Nsp", "params_a_knots",
        "params_a_cx", "params_a_cc"} <= set(bp):
        return {k: bp[k] for k in ("params_a_k", "params_a_Nsp",
                                   "params_a_knots", "params_a_cx",
                                   "params_a_cc")}
    return {}


def audit_spin(name, base, spin, fid=None):
    s = {}
    # Upstream cap (eval_reference.py:426-448): @helper proxies eagerly build
    # order-4 derivative towers at import; cap at requested order 0 for this
    # call while _inline_helpers still reaches named multiindexes on demand.
    import helper as _helper_mod
    _orig = _helper_mod.Helper.ensure_order
    set_uncapped_ensure_order(_orig)

    def _capped(self, order):
        return _orig(self, min(order, 0))
    _helper_mod.Helper.ensure_order = _capped
    try:
        return _audit_spin_inner(name, base, spin, fid, s)
    finally:
        _helper_mod.Helper.ensure_order = _orig


def _audit_spin_inner(name, base, spin, fid, s):
    try:
        mod = _import_functional(base, macro_name=name)
    except Exception as e:
        s['import'] = 'ERR:' + str(e)[:120]
        return s
    s['import'] = 'ok'
    s['module'] = base
    s['runtime'] = runtime_thresholds(name, spin, fid)
    try:
        s['dim_source'] = L._detect_dimension(mod)
    except Exception as e:
        s['dim_source'] = 'ERR:' + str(e)[:80]
    try:
        s['dens_src'] = _read_dens_threshold(name)
    except Exception as e:
        s['dens_src'] = 'ERR:' + str(e)[:80]
    s['zeta_src'] = 2.220446049250313e-16  # initialized DBL_EPSILON (functionals.c:366)
    # L1: genuinely source-only (no pylibxc anywhere in these paths)
    try:
        l1 = dict(_read_parameters(name, mod))
    except Exception as e:
        l1 = {}
        s['l1_err'] = str(e)[:120]
    try:
        cam_src = dict(cam_source_only(name))
    except Exception as e:
        cam_src = {}
        s['cam_src_err'] = str(e)[:120]
    # L2: resolver (runtime CAM allowed) + computed-key precedence
    try:
        resolved = dict(resolved_params(name, spin))
        computed = set(computed_param_keys(name, spin))
    except Exception as e:
        resolved, computed = {}, set()
        s['resolve_err'] = str(e)[:120]
    # Standalone CAM fallback (eval_reference.py:528-534)
    try:
        _cam_own_all = dict(_read_cam_defaults(name))
    except Exception:
        _cam_own_all = {}
    # Assemble records + subs BEFORE kernel so the _vxc guard below still
    # records initialized bindings (no epsilon exists there: no primal proof).
    subs_l1 = {_DENS_SYM: sp.Float(s['dens_src'] if isinstance(
        s.get('dens_src'), float) else 1e-20, 80),
        _ZETA_SYM: sp.Float(2.220446049250313e-16, 80)}
    subs_l1.update(_C_CONSTANTS)
    l1rec = {}
    for sym, v in l1.items():
        subs_l1[sym] = sp.Float(float(v), 80)
        l1rec[str(sym)] = repr(float(v))
    for sym, v in cam_src.items():
        subs_l1[sym] = sp.Float(float(v), 80)
    s['L1_source_only'] = {'n_params': len(l1rec),
                           'params': l1rec,
                           'cam_src': {str(k): float(v)
                                       for k, v in cam_src.items()}}
    cam_own = {}
    subs = dict(subs_l1)
    for _k, _v in _cam_own_all.items():
        if _k not in subs:
            subs[_k] = sp.Float(float(_v), 80)
            cam_own[str(_k)] = float(_v)
    s['L1b_cam_own'] = cam_own
    bound_names = {x.name for x in subs if isinstance(x, sp.Symbol)}
    l2rec = {}
    for pname, pval in resolved.items():
        if pname not in computed and pname in bound_names:
            continue  # L1 stands; resolver must not perturb it
        sv = pval.strip()
        if sv.startswith("["):
            for i, item in enumerate(sv[1:-1].split(",")):
                try:
                    fv = float(item)
                except ValueError:
                    continue
                key = sp.Symbol("%s[%d]" % (pname, i), real=True)
                subs[key] = sp.Float(fv, 80)
                l2rec["%s[%d]" % (pname, i)] = sv
        else:
            try:
                fv = float(sv)
            except ValueError:
                continue
            sym = getattr(mod, pname, None)
            key = (sym if isinstance(sym, sp.Symbol)
                   else sp.Symbol(pname, real=True))
            subs[key] = sp.Float(fv, 80)
            l2rec[pname] = sv  # raw exact string preserved
    s['L2_resolver'] = {'n': len(l2rec), 'raw_values': l2rec,
                        'computed_keys': sorted(computed),
                        'note': 'runtime CAM allowed; not source-only'}
    _spline = _spline_table_keys(name, spin)
    if _spline:
        # Initialized spline state for the prototype ticket: raw built values
        # for k/Nsp/knots/cx/cc alongside the unresolved params pointer leaf.
        s['params_opaque'] = ('bspline C-struct pointer: no numeric default; '
                              'real params symbol left free, no evaluator invoked')
        s['spline_state_readback'] = _spline
    elif _spline is None and 'built_err' not in s:
        s['spline_state_unreadable'] = True
    signal.alarm(120)
    try:
        if getattr(mod, 'TYPE', '').endswith('_vxc'):
            try:
                bp = dict(_built_parameters(name, spin))
            except Exception as e:
                bp = {}
                s['built_err'] = str(e)[:120]
            s['L3_built'] = {'raw': dict(bp), 'note': 'initialized readback snapshot; no epsilon target'}
            s['loose_after_L1'] = 'N/A-no-epsilon-target'
            s['loose_after_L1L2'] = 'N/A-no-epsilon-target'
            s['source_only_clean'] = 'N/A-no-epsilon-target'
            s['zk'] = 'NO_EXC_POTENTIAL_ONLY'
            s['proof_complete'] = True
            return s
        rho, sig, lapl, tau, fields, _ = _kernel_outputs(mod, spin, 0,
                                                         derivs=False,
                                                         defer_lower=True)
        eps = fields['zk'][0]  # epsilon; rho*epsilon = ntot*f
        s['lowering'] = 'deferred: my_piecewise3/5 retained per outputs.py:30-39'
        arg_syms = list(rho) + list(sig) + list(lapl) + list(tau)
        arg_set = set(arg_syms)
        def _loose(e):
            return sorted({str(x) for x in _dag_nodes(e)
                           if isinstance(x, sp.Symbol) and x not in arg_set})
        # (1) source-only-clean proof: actual _dag_xreplace(eps, L1 bindings)
        # BEFORE any runtime CAM fallback / resolver / built fills.
        es_l1 = _dag_xreplace(eps, subs_l1)
        s['loose_after_L1'] = _loose(es_l1)
        s['source_only_clean'] = not s['loose_after_L1']
        # threshold_subs with eval_reference precedence: subs already holds
        # dens/zeta <- C consts <- L1 params <- L1 cam-src <- L1b own-CAM <-
        # L2 resolver (computed keys override; else only unbound keys).
        es1 = _dag_xreplace(eps, subs)
        s['loose_after_L1L2'] = _loose(es1)
        # L3: built readback, ONLY for symbols still loose
        s['L3_built'] = {}
        loose1 = s['loose_after_L1L2']
        if loose1:
            try:
                bp = dict(_built_parameters(name, spin))
            except Exception as e:
                bp = {}
                s['built_err'] = str(e)[:120]
            s['L3_built'] = {'raw': {k: bp[k] for k in sorted(bp)
                                     if k in loose1 or any(
                                         k == x.split('[')[0]
                                         for x in loose1)}}
            scalars, indexed = {}, {}
            syms = {x for x in _dag_nodes(es1)
                    if isinstance(x, sp.Symbol) and str(x) in loose1}
            for x in syms:
                am = re.match(r'(params_a_\w+)\[(\d+)\]$', x.name)
                if am:
                    indexed.setdefault(am.group(1), []).append(
                        (int(am.group(2)), x))
                elif x.name in bp and not bp[x.name].startswith('['):
                    scalars[x] = bp[x.name]
            fill, fillraw = {}, {}
            for sym, v in scalars.items():
                fill[sym] = sp.Float(float(v), 80)
                fillraw[str(sym)] = {'raw': v, 'float': float(v)}
            for bkey, uses in indexed.items():
                body = bp.get(bkey)
                if not body or not body.startswith('['):
                    continue
                items = [t.strip() for t in body[1:-1].split(',') if t.strip()]
                hi = max(k for k, _ in uses)
                lo = min(k for k, _ in uses)
                if hi == len(items) and lo >= 1:
                    origin = 1
                elif hi <= len(items) - 1:
                    origin = 0
                else:
                    continue
                for k, sym in uses:
                    fill[sym] = sp.Float(float(items[k - origin]), 80)
                    fillraw[str(sym)] = {'raw': body,
                                         'float': float(items[k - origin]),
                                         'origin': origin}
            s['L3_built']['fill_values'] = fillraw
            es2 = _dag_xreplace(es1, fill) if fill else es1
        else:
            es2 = es1
        # (2) case21: real params symbol left free, no Symbol=0 binding, no
        # evaluator invoked; 'params' stays a genuine still_unbound leaf with
        # params_opaque metadata. No blanket 'params' exclusion anywhere.
        still = _loose(es2)
        s['zk'] = 'ok'
        s['still_unbound'] = still
        s['proof_complete'] = not still
    except TO:
        s['zk'] = 'TIMEOUT>60s'
        s['proof_complete'] = False
        s['proof_note'] = ('primal max_order=0 derivs=False single build; '
                           'UNRESOLVED prerequisite, not coverage')
    except Exception as e:
        s['zk'] = 'ERR:' + str(e)[:160]
        s['proof_complete'] = False
    finally:
        signal.alarm(0)
    return s


def registry():
    key_of = {}
    for line in open(os.path.join(_SRC, 'funcs_key.c')):
        m = re.search(r'\{"([^"]+)",\s*(\d+)\}', line)
        if m:
            key_of.setdefault(int(m.group(2)), []).append(m.group(1))
    infos = {}
    for f in sorted(glob.glob(os.path.join(_SRC, '*.c'))):
        text = open(f).read()
        for m in re.finditer(
                r'xc_func_info_type\s+xc_func_info_(\w+)\s*=\s*\{'
                r'\s*(XC_[A-Z0-9_]+)', text):
            iname, numdef = m.group(1), m.group(2)
            fid = None
            for gf in [f] + glob.glob(os.path.join(_SRC, '*.h')):
                hm = re.search(r'#define\s+' + re.escape(numdef)
                               + r'\s+(\d+)', open(gf).read())
                if hm:
                    fid = int(hm.group(1))
                    break
            fam = re.search(r'XC_FAMILY_([A-Z_]+)', text[m.start():m.start()
                                                         + 2000])
            kind = re.search(r'\n\s*XC_(EXCHANGE|CORRELATION|'
                             r'EXCHANGE_CORRELATION|KINETIC)',
                             text[m.start():m.start() + 2000])
            infos[iname] = {'fid': fid, 'info': iname,
                            'file': os.path.basename(f),
                            'family': fam.group(1) if fam else '?',
                            'kind': kind.group(1) if kind else '?'}
    bykey = {}
    for iname, r in infos.items():
        if r['fid'] is not None:
            aliases = sorted(key_of.get(r['fid'], [iname]))
            for k in aliases:
                bykey[k] = dict(r, key=k, aliases=aliases)
    return bykey


def classify(name, bykey, comp_names=()):
    if name in comp_names:
        return 'mix_only', None  # finalized CompositeOracle owns these 154
    try:
        _find_mpl(name)
        return 'primal', name
    except FileNotFoundError:
        pass
    try:
        _, text, _, _ = _resolve_source(name)
    except Exception:
        text = ''
    init = (bykey.get(name) or {}).get('info', name) + '_init'
    body = ''
    m = re.search(r'\b' + re.escape(init) + r'\s*\([^)]*\)\s*\{', text or '')
    if m:
        depth = 0
        for i in range(m.end() - 1, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    body = text[m.end():i]
                    break
    if 'xc_mix_init' in body:
        return 'mix_only', None
    try:
        base, _, _ = _resolve(name)
        _find_mpl(base)
        return 'primal', base
    except Exception:
        return 'mix_only', None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(_HERE, 'oracle-primal-ledger.json'))
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--only', default=None)
    ap.add_argument('--composite',
                    default=os.path.join(_HERE, 'oracle-composites.json'))
    a = ap.parse_args()
    bykey = registry()
    names = pylibxc.util.xc_available_functional_names()
    if a.only:
        names = [n for n in names if n in a.only.split(',')]
    out = {'meta': {}, 'rows': {}}
    if a.resume and os.path.exists(a.out):
        out = json.load(open(a.out))
    out['meta'].update({
        'n_runtime_names': len(names), 'n_unique': len(set(names)),
        'dup_names': sorted(k for k, c in collections.Counter(names).items()
                            if c > 1),
        'libxc_pin': '7d236789c2a4521270eeaa41d06e0d721ef56abd',
        'method': 'full-substitution + Helper.ensure_order cap(0) '
                  '(eval_reference.py:426-448): L1 source-only clean proof, '
                  'L1b own-CAM, L2 resolver, L3 built last-resort; zk epsilon '
                  'max_order=0 derivs=False; zeta=DBL_EPSILON initialized; '
                  '154 composites via CompositeOracle'})
    comp = {}
    if a.composite and os.path.exists(a.composite):
        for rec in json.load(open(a.composite)):
            comp.setdefault(rec['name'], []).append(rec)
    comp_names = set(comp)
    for i, name in enumerate(names):
        if name in out['rows'] and out['rows'][name].get('v') == 4:
            continue
        r = bykey.get(name, {})
        cls, base = classify(name, bykey, comp_names)
        row = {'fid': r.get('fid'), 'info': r.get('info'),
               'family': r.get('family'), 'kind': r.get('kind'),
               'aliases': r.get('aliases', [name]),
               'base': base, 'cls': cls, 'v': 4, 'spins': {}}
        if cls == 'mix_only':
            row['composite'] = comp.get(name, 'see oracle-composites.json')
        else:
            for spin in (1, 2):
                row['spins'][spin] = audit_spin(name, base, spin, r.get('fid'))
        out['rows'][name] = row
        if (i + 1) % 25 == 0:
            json.dump(out, open(a.out, 'w'))
            print('%d/%d done' % (i + 1, len(names)), flush=True)
    json.dump(out, open(a.out, 'w'), indent=1)
    print('done', len(out['rows']))


if __name__ == '__main__':
    main()
