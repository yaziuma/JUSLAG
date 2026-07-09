"""Threshold comparison logic tests.

Tests for the 4-condition threshold comparison:
  fixed ±0.10 / ±0.08 / ±0.06 / Adaptive
"""
from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

from juslag.config import ExecutionCostConfig, TaxConfig
from juslag.metrics import apply_tax_model, compute_performance
from juslag.portfolio import build_portfolio_returns_detail
from juslag.signal import ADAPTIVE_LONG_THRESHOLDS, resolve_thresholds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal_df(n: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (signal_df, jp_oc) with 4 tickers, signals spread ±0.05..±0.15."""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    sig = pd.DataFrame(
        {
            "A": [0.15] * n,   # strong LONG candidate (above 0.10 and 0.08 and 0.06)
            "B": [0.07] * n,   # passes 0.06 only
            "C": [-0.07] * n,  # SHORT candidate: passes 0.06 only
            "D": [-0.15] * n,  # strong SHORT candidate
        },
        index=idx,
    )
    jp_oc = pd.DataFrame(
        {
            "A": [0.01] * n,
            "B": [0.01] * n,
            "C": [-0.01] * n,
            "D": [-0.01] * n,
        },
        index=idx,
    )
    return sig, jp_oc


# ---------------------------------------------------------------------------
# Logic tests
# ---------------------------------------------------------------------------

def test_higher_threshold_fewer_tradeable_days() -> None:
    """Fixed ±0.10 should produce fewer (or equal) tradeable days than ±0.08."""
    sig, jp_oc = _make_signal_df(10)
    exec_cfg = ExecutionCostConfig()
    detail10 = build_portfolio_returns_detail(sig, jp_oc, q=0.25, execution_costs=exec_cfg, min_long_signal=0.10, max_short_signal=-0.10)
    detail08 = build_portfolio_returns_detail(sig, jp_oc, q=0.25, execution_costs=exec_cfg, min_long_signal=0.08, max_short_signal=-0.08)
    # ±0.10 must have ≤ tradeable days compared to ±0.08
    assert len(detail10) <= len(detail08)


def test_lower_threshold_passes_weak_signals() -> None:
    """Fixed ±0.06 should pass signals that ±0.10 would block."""
    idx = pd.date_range("2024-01-01", periods=4, freq="B")
    # Only B and C pass 0.06 but not 0.10
    sig = pd.DataFrame(
        {"A": [0.07, 0.07, 0.07, 0.07], "B": [0.03, 0.03, 0.03, 0.03],
         "C": [-0.07, -0.07, -0.07, -0.07], "D": [-0.03, -0.03, -0.03, -0.03]},
        index=idx,
    )
    jp_oc = pd.DataFrame({"A": [0.01]*4, "B": [0.01]*4, "C": [-0.01]*4, "D": [-0.01]*4}, index=idx)
    exec_cfg = ExecutionCostConfig()
    detail06 = build_portfolio_returns_detail(sig, jp_oc, q=0.25, execution_costs=exec_cfg, min_long_signal=0.06, max_short_signal=-0.06)
    detail10 = build_portfolio_returns_detail(sig, jp_oc, q=0.25, execution_costs=exec_cfg, min_long_signal=0.10, max_short_signal=-0.10)
    # ±0.06 passes A (0.07 >= 0.06), ±0.10 fails both
    assert len(detail06) >= len(detail10)


def test_adaptive_high_vol_uses_lower_threshold() -> None:
    """Adaptive in high_vol returns 0.06 threshold — same as fixed ±0.06."""
    long_th, short_th = resolve_thresholds("high_vol", 0.10, -0.10, adaptive=True)
    assert long_th == ADAPTIVE_LONG_THRESHOLDS["high_vol"]
    assert long_th == 0.06


def test_adaptive_low_vol_uses_higher_threshold() -> None:
    """Adaptive in low_vol returns 0.12 threshold — stricter than fixed ±0.10."""
    long_th, short_th = resolve_thresholds("low_vol", 0.10, -0.10, adaptive=True)
    assert long_th == ADAPTIVE_LONG_THRESHOLDS["low_vol"]
    assert long_th > 0.10


def test_compute_performance_cost_drag_computable() -> None:
    """gross_ar - net_pre_ar gives cost_drag that's non-negative for positive costs."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2022-01-03", periods=252, freq="B")
    gross_r = pd.Series(rng.normal(0.001, 0.01, 252), index=idx)
    # cost: constant 1 bps daily drag
    net_r = gross_r - 0.0001

    perf_gross = compute_performance(gross_r, "gross")
    perf_net = compute_performance(net_r, "net")

    gross_ar = float(perf_gross["AR(%)"])
    net_ar = float(perf_net["AR(%)"])
    cost_drag = gross_ar - net_ar

    assert cost_drag >= 0.0
    # All required keys for judge_backtest are present
    for key in ("AR(%)", "Risk(%)", "R/R", "MDD(%)", "N_days"):
        assert key in perf_gross
        assert key in perf_net
