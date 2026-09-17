from __future__ import annotations

import pandas as pd
import pytest

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
