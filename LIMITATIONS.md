# TT-XLA backend limitations (verified findings only)

Environment: Python 3.12, JAX/JAXlib 0.7.1, TT-XLA `pjrt-plugin-tt==1.5.0.dev20260831000501`, Equinox 0.13.0, NumPy >= 2.0, device Blackhole (`TTDevice(id=0, arch=Blackhole)`). `uv sync --extra tt-xla` succeeds.

This file tracks **only tested findings** — not a complete API audit. Each entry separates **observed** (command + error actually seen) from **source explanation** (why the code says so).

| API | Impact on dftax | Evidence | Status | Workaround |
|-----|-----------------|----------|--------|------------|
| `jnp.linalg.eigh` on `tt` platform | TT-XLA still has no `eigh` lowering. Concrete eager paths use `dftax.ks.eigh.eigh`; KS integral construction and `scf()` run on CPU when arrays are on TT, with SCF orbital/density arrays returned to TT. **Observed:** `JAX_PLATFORMS=tt,cpu uv run --extra tt-xla python examples/01_water_rks.py` completes for LDA/PBE/PBE0/B3LYP; `JAX_PLATFORMS=tt` alone cannot expose the CPU backend. **Remaining limitation:** traced/vmapped Eigh callsites (`ks/batched.py`, `ks/implicit.py`, force/geometry rebuilds, `_rik_cholesky`) cannot use eager transfers; `pure_callback` is unsupported on TT. | Eager workaround verified; transformed TT paths unsupported | Include both `tt,cpu` in `JAX_PLATFORMS`; run traced workflows on CPU. |
| Internal `jax._src.lax.linalg.eigh_jacobi` custom call `Eigh` on `tt` | Not a usable fallback. **Observed:** a direct TT smoke test of this path fails with `failed to legalize operation 'stablehlo.custom_call'`. **Source:** `_eigh_jacobi_lowering_rule` emits `mlir.custom_call("Eigh", ...)` with `api_version=1` and a bare `mlir.register_lowering(eigh_jacobi_p, ...)` with no platform restriction (`.venv/lib/python3.12/site-packages/jax/_src/lax/linalg.py:1067-1104`, custom call at `:1091-1098`) — i.e. it lowers to an XLA `Eigh` custom call the TT backend does not legalize. Note it is private (`jax._src`, docstring "Used as a subroutine of QDWH-eig on TPU", `:1047-1053`), not public `jax.lax.linalg` API. | Direct observation + source | Open, do not depend on | None; same CPU-offload workaround as above applies. |
| Basic TT execution (`jit`, device query) | Works — the backend itself is functional; only specific primitives (above) are missing. **Observed:** `jit(lambda x: x+1, backend='tt')` runs; `jax.devices('tt')` returns `[TTDevice(id=0, arch=Blackhole)]`. | Direct observation | Working | — |

## Adding a finding

Keep entries minimal and verifiable:

```markdown
| <API> | <which dftax path it blocks> | Observed: <exact command + error>. Source: <local path:lines>. | Open/Working | <workaround or —> |
```

Rules: reproduce first (`JAX_PLATFORMS=tt uv run --extra tt-xla ...`); cite local source paths with line numbers, not docs memory; mark inference as inference; never widen this file into an untested compatibility claim.
