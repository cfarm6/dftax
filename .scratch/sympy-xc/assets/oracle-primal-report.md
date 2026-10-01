# Primal/default audit — complete ledger (709/709)

## Files (all `.scratch/sympy-xc/assets/`)
- `oracle-primal-audit.py` — audit script (single runnable deliverable)
- `oracle-primal-ledger.json` — complete ledger, 709 rows
- `oracle-composites.json` — finalized CompositeOracle, 154 mix-only IDs

## Census
- Runtime: 725 names, **709 unique** (15 dup IDs incl. 1 triple); per-identity `aliases` (sorted `funcs_key.c` key list for the identity's fid) recorded on every row.
- Ledger: **709 rows = 555 primal + 154 mix_only** (composite classifier). Zero missing, zero timeouts, zero import errors.
- Spins: 1094 ok+complete, 14 NO_EXC_POTENTIAL_ONLY (7 `_vxc` IDs × 2 spins: potential-valued f has no zk at max_order=0), 2 with genuine `params` leaf (1 bspline ID × 2 spins).
- Source-only substitution leaves zero loose symbols in 1014 energy spin records. Of the 82 remaining energy spin records, initialized-CAM/resolver/struct fills close 80; the two CASE21 records retain the actual opaque `params` leaf. The 14 potential-only records have no epsilon target.

## Root cause of prior incompleteness
`libxc_codegen._GEN_MAX_ORDER` defaults to 4; `@helper` proxies eagerly build the order-4 derivative tower at import. `_kernel_outputs(max_order=0)` never capped it, so the audit built an unwanted derivative tower (gga_x_wpbeh: 734/800 s in ensure_order). Fix reuses the exact upstream pattern (`eval_reference.py:426-448`): cap `Helper.ensure_order` at requested order 0 for the call duration, publish the original via `dag.set_uncapped_ensure_order` so `_inline_helpers` still reaches named multiindexes on demand.

## Method (per direct ID × spin 1,2)
- Bindings assembled BEFORE kernel: L1 source-only (`_read_parameters` + pure-C CAM parse + `_C_CONSTANTS` + dens/zeta thresholds), L1b own-CAM fallback via `_read_cam_defaults` (runtime `xc_hyb_cam_coef` authority for source-silent hybrids), L2 `resolved_params` with `computed_param_keys` override-else-only-unbound precedence (L1 never perturbed). L3 `_built_parameters` readback only for post-L1L2 loose symbols, whole-base origin inference.
- Proof target: `fields['zk'][0]` epsilon (rho*epsilon = ntot*f never the target); `defer_lower=True`; residual = ALL Symbol leaves minus kernel ingredient args via `_dag_xreplace`/`_dag_nodes` (dag.py:61 — no bound-variable constructs reach the walker). No blanket `params` exclusion anywhere.
- `loose_after_L1` + `source_only_clean` come from actual `_dag_xreplace(eps, L1 source-only bindings)` BEFORE L1b/L2/L3; `loose_after_L1L2` after L1b+L2; exact L1 raw + L1b/L2/L3 numeric fills recorded per row.
- `_vxc` rows record full L1/L1b/L2/L3 initialized bindings, then `NO_EXC_POTENTIAL_ONLY` with no epsilon target and no primal proof (loose fields marked `N/A-no-epsilon-target`).
- Conventions: zeta = initialized DBL_EPSILON 2.220446049250313e-16 (functionals.c:366), recorded as `zeta_src`; runtime per-spin thresholds/dim/cam/hyb_exx kept separately. case21 `params` is the real C-struct pointer symbol left free (no Symbol=0 binding, no evaluator invoked); initialized spline state (`params_a_k/Nsp/knots/cx/cc` raw built values, the exact table `mpmath_impls.py:273-344` rebuilds xbspline/cbspline from) retained as `spline_state_readback` alongside `params_opaque` metadata.

## Genuine unresolved leaves
- Only `hyb_gga_xc_case21` × 2 spins: `still_unbound: ['params']` (C bspline struct pointer, no numeric default exists) with initialized `spline_state_readback` (k/Nsp/knots/cx/cc) for the prototype ticket's pure-JAX representation decision. L1-loose there also shows `params_a_ax/gammac/gammax`, all bound by L2/L3 — final residual is just `params`.

## Command (reproduce; exact standalone full-audit invocation)
- `cd /tmp/libxcsrc/libxc && LD_LIBRARY_PATH=/tmp/xcoracle-po/lib /tmp/xcoracle-po/venv/bin/python /home/carson/dftax/.scratch/sympy-xc/assets/oracle-primal-audit.py --out /home/carson/dftax/.scratch/sympy-xc/assets/oracle-primal-ledger.json`
- Observed stdout tail: `700/725 done`, `725/725 done`, `done 709` (EXIT 0; ~84 s single process; `--out` absolute so the ledger lands in assets, not the process cwd).
