from __future__ import annotations

import numpy as np
import pandas as pd


def build_prior_eigenvectors(us_tickers: list[str], jp_tickers: list[str], us_cyclical: dict[str, int], jp_cyclical: dict[str, int]) -> np.ndarray:
    """Build V0 prior eigenvectors: global, country spread, cyclic-defensive."""

    n_u = len(us_tickers)
    n_j = len(jp_tickers)
    n = n_u + n_j

    def normalize(v: np.ndarray) -> np.ndarray:
        return v / np.linalg.norm(v)

    def gram_schmidt(v: np.ndarray, basis: list[np.ndarray]) -> np.ndarray:
        for b in basis:
            v = v - np.dot(v, b) * b
        return normalize(v)

    v1 = normalize(np.ones(n))
    v2_raw = np.array([1.0] * n_u + [-1.0] * n_j)
    v2 = gram_schmidt(v2_raw, [v1])
    cyc = np.array([us_cyclical[t] for t in us_tickers] + [jp_cyclical[t] for t in jp_tickers], dtype=float)
    v3 = gram_schmidt(cyc, [v1, v2])
    return np.column_stack([v1, v2, v3])


def build_prior_exposure(cc_full: pd.DataFrame, v0: np.ndarray) -> np.ndarray:
    """Build C0 from long-window correlation projected onto prior subspace."""
    r = cc_full.values
    mu = r.mean(axis=0, keepdims=True)
    sig = r.std(axis=0, keepdims=True) + 1e-10
    z = (r - mu) / sig
    c_full = z.T @ z / len(z)

    d0 = np.diag(np.diag(v0.T @ c_full @ v0))
    c0_raw = v0 @ d0 @ v0.T

    diag_vals = np.diag(c0_raw)
    diag_vals = np.where(np.abs(diag_vals) < 1e-12, 1.0, diag_vals)
    d_inv_sqrt = np.diag(1.0 / np.sqrt(diag_vals))
    c0 = d_inv_sqrt @ c0_raw @ d_inv_sqrt
    np.fill_diagonal(c0, 1.0)
    return c0
