from __future__ import annotations

import pandas as pd
import pytest
import runpy

from juslag.cache import PriceCache
from juslag.portfolio import build_portfolio_with_strategy_rule
from juslag.services.backtest import BacktestParams, run_backtest_service
from juslag.strategies.context import StrategyContext
from juslag.strategies.preopen_no_gap import PreopenNoGap


def _context(rotation: str | None, gap: float | None) -> StrategyContext:
    return StrategyContext(
        signal_date="2026-05-01",
        candidate_signal_strength=None,
        open_gap=gap,
        long_gap=gap,
        short_gap=gap,
        trend_regime=None,
        vol_regime=None,
        rotation_regime=rotation,
    )


def test_preopen_rule_ignores_open_gap() -> None:
    rule = PreopenNoGap()
    assert rule.decide(_context("mid_rotation", None)).selected_strategy == "curr_oc"
    assert rule.decide(_context("mid_rotation", 0.20)).selected_strategy == "curr_oc"
    assert rule.decide(_context("weak_rotation", None)).action == "skip"


def test_preopen_portfolio_is_invariant_to_execution_day_gap() -> None:
    dates = pd.bdate_range("2025-01-02", periods=4)
    tickers = [f"T{i}" for i in range(6)]
    signals = pd.DataFrame({t: [float(6 - i)] * 3 for i, t in enumerate(tickers)}, index=dates[:3])
    jp_oc = pd.DataFrame({t: [0.002 * (i - 2)] * 4 for i, t in enumerate(tickers)}, index=dates)
    regime = pd.DataFrame({"rotation_regime": ["mid_rotation"] * 3}, index=dates[:3])
    no_gap = pd.DataFrame(0.0, index=dates, columns=tickers)
    extreme_gap = pd.DataFrame(0.20, index=dates, columns=tickers)

    first = build_portfolio_with_strategy_rule(signals, jp_oc, no_gap, regime, PreopenNoGap())
    second = build_portfolio_with_strategy_rule(signals, jp_oc, extreme_gap, regime, PreopenNoGap())

    assert not first.empty
    pd.testing.assert_frame_equal(first, second)


def test_research_rule_id_must_match_params(tmp_path) -> None:
    with pytest.raises(ValueError, match="research_rule.rule_id"):
        run_backtest_service(
            BacktestParams(strategy_rule_id="rule_406_no_flip"),
            PriceCache(tmp_path / "prices.db"),
            research_rule=PreopenNoGap(),
        )


def test_daily_decomposition_separates_common_and_unique_dates() -> None:
    decompose = runpy.run_path("scripts/reports/compare_preopen_baseline.py")["decompose_daily_returns"]
    current = [
        {"date": "2026-05-01", "gross_return": 0.03, "net_pre_tax_return": 0.02},
        {"date": "2026-05-07", "gross_return": 0.01, "net_pre_tax_return": 0.00},
    ]
    preopen = [
        {"date": "2026-05-01", "gross_return": 0.01, "net_pre_tax_return": 0.00},
        {"date": "2026-05-08", "gross_return": 0.02, "net_pre_tax_return": 0.01},
    ]

    result = decompose(current, preopen)

    assert result["common"] == {"days": 1, "gross_delta_sum_bps": 200.0, "net_delta_sum_bps": 200.0}
    assert result["current_only"] == {"days": 1, "gross_delta_sum_bps": 100.0, "net_delta_sum_bps": 0.0}
    assert result["preopen_only"] == {"days": 1, "gross_delta_sum_bps": -200.0, "net_delta_sum_bps": -100.0}
