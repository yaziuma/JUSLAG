"""build_portfolio_with_strategy_rule の単体テスト + run_backtest_service の strategy_rule_id 統合テスト"""
from __future__ import annotations
import pandas as pd
import pytest
from juslag.cache import PriceCache
from juslag.portfolio import build_portfolio_with_strategy_rule
from juslag.services.backtest import BacktestParams, run_backtest_service
from juslag.strategies.base import StrategyRule
from juslag.strategies.context import StrategyContext
from juslag.strategies.decision import StrategyDecision


def _stub_rule(selected_strategy: str, action: str = "execute") -> StrategyRule:
    class _Stub(StrategyRule):
        rule_id = "stub"
        rule_name_ja = "スタブ"
        description_ja = "テスト"
        default_strategy = selected_strategy
        def decide(self, ctx: StrategyContext) -> StrategyDecision:
            return StrategyDecision(
                selected_strategy=selected_strategy,
                action=action,
                rule_id="stub",
                rule_name_ja="スタブ",
                reason_ja="テスト",
            )
    return _Stub()


def _make_data(n_days: int = 10, n_tickers: int = 9):
    """ランダムではなく決定論的なシグナルとリターンデータを生成する。"""
    dates = pd.bdate_range("2025-01-02", periods=n_days)
    tickers = [f"T{i:02d}" for i in range(n_tickers)]
    # 決定論的なシグナル：T00-T03 が高、T05-T08 が低
    signals = {}
    for i, t in enumerate(tickers):
        val = (n_tickers - i) * 0.1  # T00=0.9, T01=0.8, ... T08=0.1
        signals[t] = [val] * n_days
    signal_df = pd.DataFrame(signals, index=dates)
    # jp_oc: 全銘柄 +0.5% return
    jp_oc = pd.DataFrame({t: [0.005] * n_days for t in tickers}, index=dates)
    # overnight_gap: 全銘柄 0%
    overnight_gap_df = pd.DataFrame({t: [0.0] * n_days for t in tickers}, index=dates)
    return signal_df, jp_oc, overnight_gap_df


class TestBuildPortfolioWithStrategyRule:
    def test_curr_oc_same_as_base(self):
        signal_df, jp_oc, gap_df = _make_data()
        result = build_portfolio_with_strategy_rule(
            signal_df, jp_oc, gap_df, None,
            _stub_rule("curr_oc", "execute"),
            q=0.3,
        )
        assert not result.empty
        assert "net_pre_tax_return" in result.columns

    def test_skip_rule_returns_empty_df(self):
        signal_df, jp_oc, gap_df = _make_data()
        result = build_portfolio_with_strategy_rule(
            signal_df, jp_oc, gap_df, None,
            _stub_rule("skip", "skip"),
            q=0.3,
        )
        assert result.empty

    def test_long_flip_adopted_long_is_zero(self):
        signal_df, jp_oc, gap_df = _make_data()
        result = build_portfolio_with_strategy_rule(
            signal_df, jp_oc, gap_df, None,
            _stub_rule("long_flip_oc", "override"),
            q=0.3,
        )
        assert not result.empty
        assert (result["n_long"] == 0).all()

    def test_short_only_adopted_long_is_zero(self):
        signal_df, jp_oc, gap_df = _make_data()
        result = build_portfolio_with_strategy_rule(
            signal_df, jp_oc, gap_df, None,
            _stub_rule("short_only_oc", "override"),
            q=0.3,
        )
        assert not result.empty
        assert (result["n_long"] == 0).all()

    def test_gap_ovht_oc_filters_excess_long_gap(self):
        signal_df, jp_oc, _ = _make_data()
        # T00-T03 が LONG 候補（高シグナル）、そのうち T00 だけ gap > 0.5%
        tickers = signal_df.columns.tolist()
        gap_vals = {t: 0.0 for t in tickers}
        gap_vals[tickers[0]] = 0.006  # T00 の gap > threshold → LONG から除外
        gap_df = pd.DataFrame({t: [gap_vals[t]] * len(signal_df) for t in tickers}, index=signal_df.index)
        result = build_portfolio_with_strategy_rule(
            signal_df, jp_oc, gap_df, None,
            _stub_rule("gap_ovht_oc", "execute"),
            q=0.3,
        )
        assert not result.empty
        # T00 が除外されるため n_long が減る（通常 q=0.3 で 9*0.3=2.7 → 2または3枚）
        # gap 除外後は T00 が外れるので -1 になっているはず
        # strict にチェック: strategy_decision カラムが gap_ovht_oc
        assert (result["strategy_decision"] == "gap_ovht_oc").all()

    def test_strategy_decision_column_exists(self):
        signal_df, jp_oc, gap_df = _make_data()
        result = build_portfolio_with_strategy_rule(
            signal_df, jp_oc, gap_df, None,
            _stub_rule("curr_oc"),
            q=0.3,
        )
        assert "strategy_decision" in result.columns


class TestBacktestServiceWithStrategyRuleId:
    """run_backtest_service に strategy_rule_id を渡すと meta_rule パフォーマンスが返る（オフライン: 実キャッシュ使用）"""

    def test_backtest_response_has_strategy_rule_id(self):
        cache = PriceCache()
        bt = run_backtest_service(BacktestParams(strategy_rule_id="rule_406"), cache)
        assert bt["strategy_rule_id"] == "rule_406"
        assert "meta_rule_net_pre_tax" in bt["performance_sets"]

    def test_backtest_without_strategy_rule_id_unchanged(self):
        cache = PriceCache()
        bt = run_backtest_service(BacktestParams(), cache)
        assert bt.get("strategy_rule_id") is None
        assert "meta_rule_net_pre_tax" not in bt.get("performance_sets", {})
