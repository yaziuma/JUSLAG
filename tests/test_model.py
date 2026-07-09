import numpy as np

from juslag.model import compute_signal_at_t


def test_compute_signal_at_t_shape_and_finite() -> None:
    l, n_u, n_j = 60, 5, 7
    n = n_u + n_j
    z_window = np.random.randn(l, n)
    z_us_t = np.random.randn(n_u)
    c0 = np.eye(n)

    out = compute_signal_at_t(z_window, z_us_t, c0, n_u=n_u, k=3, lam=0.9)
    assert out.shape == (n_j,)
    assert np.isfinite(out).all()


def test_compute_signal_at_t_extreme_inputs() -> None:
    l, n_u, n_j = 10, 3, 4
    n = n_u + n_j
    z_window = np.full((l, n), 1e9)
    z_window[0, 0] = np.nan
    z_us_t = np.array([np.inf, -np.inf, np.nan])
    c0 = np.eye(n)

    out = compute_signal_at_t(z_window, z_us_t, c0, n_u=n_u, k=2, lam=0.5)
    assert out.shape == (n_j,)
    assert np.isfinite(out).all()
