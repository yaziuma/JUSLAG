from __future__ import annotations

import numpy as np
from scipy.linalg import eigh


def compute_propagation_matrix(v_u: np.ndarray, v_j: np.ndarray) -> np.ndarray:
    """Compute propagation matrix B = V_J @ V_U.T."""
    return v_j @ v_u.T


def compute_signal_at_t(z_window: np.ndarray, z_us_t: np.ndarray, c0: np.ndarray, n_u: int, k: int = 3, lam: float = 0.9) -> np.ndarray:
    """Compute JP signal vector via subspace-regularized PCA."""
    z_window = np.nan_to_num(z_window, nan=0.0, posinf=0.0, neginf=0.0)
    z_us_t = np.nan_to_num(z_us_t, nan=0.0, posinf=0.0, neginf=0.0)

    c_t = z_window.T @ z_window / max(len(z_window), 1)
    np.fill_diagonal(c_t, 1.0)

    c_reg = (1.0 - lam) * c_t + lam * c0
    c_reg = np.nan_to_num(c_reg, nan=0.0)
    np.fill_diagonal(c_reg, 1.0)

    _, eigvecs = eigh(c_reg, check_finite=False)
    v_k = eigvecs[:, -k:]

    v_u = v_k[:n_u, :]
    v_j = v_k[n_u:, :]

    f_t = v_u.T @ z_us_t
    return v_j @ f_t
