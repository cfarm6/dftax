# Whole-catalog Libxc coverage and missing physics

- Map: [Plan a separate Libxc XC backend with maximal functional coverage](https://github.com/cfarm6/dftax/issues/2).
- This ticket: [Audit whole-catalog Libxc coverage and missing physics](https://github.com/cfarm6/dftax/issues/13) (claimed by cfarm6; planning only).
- Pins: Libxc `7d236789c2a4521270eeaa41d06e0d721ef56abd` (runtime 7.1.2), libxckernel `50aff7cfa0635e1755681715b155bc503e0b2b1f` (generation tooling only).
- Boundary: [Decide libxckernel's role in JAX XC](https://github.com/cfarm6/dftax/issues/6) — separate XC functional backend vs XC grid execution modes; libxckernel is never a formula or host-physics provider.
- Prerequisite oracle: [Provision pinned Libxc default-parameter oracle](https://github.com/cfarm6/dftax/issues/12) — `/tmp/xcoracle-po`, 709-identity ledger, 154 composite readbacks.
- Companion audits: [Inventory Libxc semilocal coverage and defaults](https://github.com/cfarm6/dftax/issues/3), [Recover faithful Libxc primal expressions](https://github.com/cfarm6/dftax/issues/4).
- License: Libxc is MPL-2.0 (`COPYING` at pin). SymPy-tree expressions carry upstream provenance; redistribution/attribution is a packaging question, not resolved here.
- Method: per-identity `src/*.c` `xc_func_info_*` flags/family/kind + `oracle-primal-ledger.json` spin outcomes + `oracle-composites.json` readbacks + pinned-source spot checks. No class excluded. Capability groupings are facts, not support policy.

## Reconciliation

709 registered identities, 725 key names (16 alias-only names, e.g. `lda_c_1d_csc`→18, `hyb_gga_xc_bhlyp`/`hyb_gga_xc_opb3lyp`→436), 709 unique ids. 555 primal + 154 worker-less composites (`cls=mix_only`, spins resolved via composites). 1094/1096 energy spin records fully bound; 7 potential-only identities (14 spin records) have no epsilon by construction; 1 spline-opaque identity (CASE21, 2 spin records) retains a genuine `params` leaf. Machine inventory: `whole-catalog-inventory.json` (709 rows, explicit ids/names/aliases/flags/thresholds/modules). Repro: `python3 whole-catalog-smoke.py whole-catalog-inventory.json` (asserts 709 unique + prints group census). Oracle smoke: isolated-env `pylibxc` CAM/VV10 readback (command in §Oracle smoke).

## Capability groups (affected ids; names in inventory rows)

- Semilocal 3D energy-defined (383): LDA/GGA/MGGA, non-hybrid, non-VV10, non-kinetic, no Laplacian. Local JAX path exists in principle (rho/sigma/tau + libxckernel `lda,gga,mgga_tau,mgga_lapl,mgga` contraction families). Blockers per-row only (defaults all bound; thresholds per-row).
- Laplacian-needing (47): 42,72,206,207,208,209,210,211,214,220,229,230,243,256,284,319,397,398,543,564,586,598,602,617,618,621,627,628,629,630,631,632,634,686,687,688,689,690,691,700,701,702,718,719,777,778,779. Native dftax has no Laplacian seam on any grid mode (scout: `dftax/energy/gto.py` values+first-grad only; `potentials.py:44-45` raises). Covered by [Specify Laplacian ingredients across every XC backend](https://github.com/cfarm6/dftax/issues/10) — no new ticket proposed. Note: MGGA `lapl_syms` plumbing ≠ dependence (r2SCAN carries `la` structurally but `free=[gaa,na,ta]`); KXC/LXC-only Laplacian rows and `mgga_x_sa_tpss` (542, sole ENFORCE_FHC) need per-row attention at conversion.
- Global hybrids (109): scalar exact-exchange fractions, no CAM/CAMY. Native `hf_coeff` seam exists; per-registration fractions/coefficients unresolved here. Includes 390 CASE21 (spline-opaque, see below).
- Range-separated erf CAM (59): 81,178,248,297,304,310,385,395,399,400,427,428,429,430,431,432,433,434,463,464,465,466,469,471,473,478,479,480,481,482,486,487,488,489,490,491,492,531,589,610,614,615,625,636,637,639,640,646,647,653,656,658,662,681,705,706,720,771,775. Native erf-omega RSH exists. Per-registration (omega,alpha,beta) + attenuated-tensor coverage is a design question — genuinely new (see decision questions). Five HSE-family rows (427,428,478,479,480) carry spelled-out `I_HAVE_*` instead of `MAPLE2C_FLAGS`; threshold correction 1e-15 noted in catalog audit.
- Yukawa CAMY (6): 455,467,468,470,588,682. No native Yukawa counterpart (scout §4). New decision question (unified attenuated-exchange design vs exclusion with reason).
- Nonlocal VV10/rVV10 tails (13): 254,255,292,466,469,531,584,585,652,658,703,704,771. Native VV10 supports only (b,c)-VV10, materialized-grid only (`dftax/energy/vv10.py`, `ks/energy.py:811-818` guard). rVV10 kernel rows (292,652,703) have no native kernel; `nlc_b/nlc_C` per-row values recorded in composites (e.g. scan_rvv10 b=15.7/C=0.0093 vs scan_vv10 b=14.0). New decision question.
- Kinetic (69): all `kind=KINETIC` (5 LDA + 51 GGA + 13 MGGA). No native KE registry/branch. No class excluded by this audit; support vs explicit-unsupported is a human decision. New decision question (kept distinct from potential-only ticket).
- Non-3D (17): 1D (18,21,26,536,537,538,600) + 2D (15,16,19,124,127,128,129,210,211,609). Native is 3D-molecular only. Dimensional contract (ingredient scaling, grid/AO support, oracle comparability) is a new decision question.
- DEVELOPMENT (13): 33,210,211,225,230,243,472,590,686,688,695,696,697. Upstream-stability caveat, not a technical blocker finding.
- Potential-only, no scalar energy (7): 160 `gga_x_lb`, 182 `gga_x_lbm`, 207 `mgga_x_bj06`, 208 `mgga_x_tb09`, 209 `mgga_x_rpp09`, 211 `mgga_x_2d_prhg07_prp10`, 599 `lda_xc_tih`. Covered by [Decide capabilities for Libxc entries without scalar energies](https://github.com/cfarm6/dftax/issues/15) — no new ticket proposed.
- Spline-opaque CASE21 (1): 390 `hyb_gga_xc_case21`. Only identity with genuine `params` leaf; initialized spline degree/basis/knots/coefficients recorded in oracle, no numeric-default fabrication. Covered by [Choose differentiable JAX spline artifacts for CASE21](https://github.com/cfarm6/dftax/issues/16) — no new ticket proposed.
- Composite-only (154): listed in inventory `composites_mix_only`; resolved via initialized composite readbacks (812 slots), not source formulas. Covered by [Specify Libxc registration and composition](https://github.com/cfarm6/dftax/issues/9) — no new ticket proposed.
- Threshold quirk: 47 `gga_c_q2d` struct 0.0 vs computed fallback; HSE-family 1e-15 corrections — conversion-design inputs.

## Explicitly verified non-findings (evidence, not repetition)

- Zero local-hybrid (NEEDS_EXX-density) entries at this pin: no `XC_FLAGS_HYB_LC/LCY` token appears in any of the 709 info structs (`hybrids.c` machinery exists but no registration sets it); KCIS hybrids (566–569) are global hybrids (scalar `exx` 0.13–0.41) + KCIS correlation. Scout's "M08/M11/MN need EXX-density" identification is therefore not reproduced — those families are global/RSH at this pin. No local-hybrid decision ticket is proposed; if a future pin adds `HYB_LC`, that reopens the question.
- M08/M11/MN12-SX rows are global or erf-CAM (e.g. 248 `hyb_mgga_x_mn12_sx` is HYB_CAM), not local hybrids.
- `STABLE` flag: 0 rows. `ON_HOST/ON_DEVICE`: 44 each, infra-only.
- `lda_c_1d_css` (18): table readback fills 10/20 params per spin (not source defaults); `gga_xc_opbe_d` (65) DEFAULT-slot and `gga_xc_kt3` (587) computed-coefficient fills resolved by oracle — prior `B-oracle` markers superseded.

## Oracle smoke

```bash
env LD_LIBRARY_PATH=/tmp/xcoracle-po/lib \
  PYTHONPATH=/tmp/xcoracle-po/cpython-3.13-linux-x86_64-gnu/lib/python3.13/site-packages \
  /tmp/xcoracle-po/venv/bin/python -c "
import pylibxc
f=pylibxc.LibXCFunctional('hyb_gga_xc_hse06',1); print('hse06 cam:', f.get_cam_coef());
g=pylibxc.LibXCFunctional('mgga_c_scan_rvv10',1); print('scan_rvv10 vv10:', g.get_vv10_coef());"
```

Observed: `hse06 cam: (0.11, 0.0, 0.25)`; `scan_rvv10 vv10: (15.7, 0.0093)`. Confirms CAM + rVV10 tails are live host-physics parameters the JAX backend must plan for, not formula content.

## Inventory smoke

```bash
cd .scratch/sympy-xc/assets && python3 whole-catalog-smoke.py whole-catalog-inventory.json
```

Observed: `identities=709 unique=709 names=725 primal=555 mix_only=154` + per-group census matching §Reconciliation. Exit 0.

## Resolution draft (factual, no policy)

The whole pinned catalog is reconciled: every one of 709 identities carries family/kind/dimension/ingredient flags, energy-vs-potential-only status, source-vs-readback default provenance, and capability-group membership. Local semilocal energy rows have bound defaults; every other row names its missing host capability (Laplacian seam, erf-CAM parameters, Yukawa kernel, rVV10 kernel, KE registry, dimensional contract, spline artifacts, restricted-capability vs unsupported status). No functional class was excluded to reach this inventory.

## Candidate new decision tickets (genuinely new; duplicates avoided)

Existing tickets already own: Laplacian grid contract (10), potential-only capabilities (15), CASE21 splines (16), registration/composition (9), numerical acceptance (11), JAX contraction prototype (14), branch-safe conversion (8), artifact boundary (7). Proposed additions:

1. Decide attenuated-exchange coverage: per-registration erf-CAM (59 rows) parameter + tensor support and Yukawa-CAMY (6 rows) kernel vs explicit-unsupported with reason. Depends on whole-catalog audit (13); blocks acceptance (11).
2. Decide nonlocal-correlation coverage: (b,c)-VV10 on non-materialized modes + rVV10 kernel (292,652,703) vs explicit-unsupported with reason. Depends on 13; blocks 11.
3. Decide kinetic-energy functional surface: registry/branch for 69 KINETIC identities vs explicit out-of-XC-energy-scope with reason. Depends on 13.
4. Decide dimensional contract: 1D (7) + 2D (10) ingredient scaling, grid/AO support, oracle comparability vs explicit-unsupported with reason. Depends on 13; related to 10/11.
5. Decide DEVELOPMENT-identity policy: 13 rows pinned vs upstream-unstable caveat. Depends on 13.

Parent owns tracker resolution, mapping, and ticket creation; no HITL decisions made here.
