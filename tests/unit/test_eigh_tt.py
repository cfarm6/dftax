import jax
import jax.numpy as jnp
import numpy as np
import pytest

from dftax.ks.eigh import eigh


def test_eigh_round_trips_batched_tt_arrays():
    try:
        device = jax.devices("tt")[0]
    except RuntimeError:
        pytest.skip("TT-XLA backend is not installed")

    a = jnp.array([[[2.0, 1.0], [1.0, 2.0]], [[4.0, 0.0], [0.0, 5.0]]])
    a = jax.device_put(a, device)
    w, v = eigh(a)

    assert next(iter(w.devices())) == device
    assert next(iter(v.devices())) == device
    cpu = jax.devices("cpu")[0]
    a_host, w_host, v_host = (
        np.asarray(jax.device_put(x, cpu)) for x in (a, w, v)
    )
    assert np.allclose(w_host, [[1.0, 3.0], [4.0, 5.0]])
    assert np.allclose(a_host @ v_host, v_host * w_host[..., None, :], atol=1e-6)
