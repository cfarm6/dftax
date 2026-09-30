"""CPU offload for symmetric eigendecomposition on TT.

The TT-XLA backend does not implement ``eigh``. This helper runs it on the
host CPU instead: a concrete array living on a ``tt`` device is transferred
to CPU, decomposed there with ``jnp.linalg.eigh``, and both outputs are
transferred back to the input device. Arrays on other platforms (including
CPU) take the plain ``jnp.linalg.eigh`` path with no transfer.

Concrete eager TT arrays only: traced inputs pass through to JAX's native
``eigh`` and remain unsupported on TT (``device_put`` is traced inside JIT,
and ``pure_callback`` is unsupported). Batched eager inputs are supported;
transfers cover the whole batch.
"""

from __future__ import annotations

import jax
import jax.numpy as jnp


def eigh(a):
    """``(w, V) = eigh(a)`` with a CPU round-trip when ``a`` lives on TT."""
    if isinstance(a, jax.core.Tracer) or not isinstance(a, jax.Array):
        return jnp.linalg.eigh(a)
    dev = next(iter(a.devices()))
    if dev.platform == "tt":
        cpu = jax.devices("cpu")[0]
        host = jax.device_put(a, cpu)
        with jax.default_device(cpu):
            w, v = jnp.linalg.eigh(host)
        return jax.device_put(w, dev), jax.device_put(v, dev)
    return jnp.linalg.eigh(a)
