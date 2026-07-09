"""
run_daily_signal_service の strategy_decision 適用統合テスト + gap日付選択単体テスト。

サービス層 (juslag.services.daily_signal) を直接呼び出し、
generate_signals_fn / get_rule_fn / pick_overnight_gap_fn の依存性注入で
決定論的なスタブを渡す（Detroit-school: 内部パッチではなく引数注入）。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from juslag.cache import PriceCache
from juslag.config import AppConfig
from juslag.services.daily_signal import pick_overnight_gap, run_daily_signal_service
from juslag.strategies.base import StrategyRule
from juslag.strategies.context import StrategyContext
from juslag.strategies.decision import StrategyDecision

_JST = ZoneInfo("Asia/Tokyo")
# 実キャッシュ (~/.juslag/prices.db) に収まる過去日付を固定して使う。
_NOW_JST = datetime(2026, 7, 8, 8, 0, 0, tzinfo=_JST)


# ---------------------------------------------------------------------------
# スタブルール ファクトリ
# ---------------------------------------------------------------------------

def _stub_rule(selected_strategy: str, action: str = "execute") -> StrategyRule:
    """常に指定した decision を返すスタブ StrategyRule。"""

    class _Stub(StrategyRule):
        rule_id = "stub"
        rule_name_ja = "スタブ"
        description_ja = "テスト用"
        default_strategy = selected_strategy

        def decide(self, context: StrategyContext) -> StrategyDecision:
            return StrategyDecision(
                selected_strategy=selected_strategy,
                action=action,
                rule_id="stub",
                rule_name_ja="スタブ",
                reason_ja=f"テスト: {selected_strategy}",
            )

    return _Stub()


def _fake_generate_signals(*args, **kwargs) -> pd.DataFrame:
    """LONG / SHORT が明確に分かれる 9-ticker シグナルを返す（実在するJPティッカー使用）。"""
    idx = pd.to_datetime(["2026-07-07"])
    return pd.DataFrame(
        {
            "1617.T": [0.40],
            "1618.T": [0.35],
            "1619.T": [0.30],
            "1620.T": [0.10],
            "1621.T": [0.00],
            "1622.T": [-0.10],
            "1623.T": [-0.30],
            "1624.T": [-0.35],
            "1625.T": [-0.40],
        },
        index=idx,
    )


def _run_daily_signal(**overrides) -> dict:
    cfg = overrides.pop("cfg", None) or AppConfig()
    cache = overrides.pop("cache", None) or PriceCache()
    kwargs = dict(
        operation_mode="development",
        now_jst=_NOW_JST,
        generate_signals_fn=_fake_generate_signals,
    )
    kwargs.update(overrides)
    return run_daily_signal_service(cfg, cache, **kwargs)


# ---------------------------------------------------------------------------
# 1. skip → execution_plan.long / short が空になる
# ---------------------------------------------------------------------------

def test_daily_signal_skip_empties_execution_plan() -> None:
    d = _run_daily_signal(get_rule_fn=lambda _: _stub_rule("skip", "skip"))

    assert d["strategy_decision"]["action"] == "skip"
    assert d["strategy_decision"]["selected_strategy"] == "skip"
    assert d["execution_plan"]["long"] == []
    assert d["execution_plan"]["short"] == []
    assert d["adopted_long_count"] == 0
    assert d["adopted_short_count"] == 0
    assert d["tradeable"] is False
    assert d["trade_block_reason"] == "strategy_rule_skip"


# ---------------------------------------------------------------------------
# 2. long_flip_oc → LONG が全て SHORT になり execution_plan.long が空
# ---------------------------------------------------------------------------

def test_daily_signal_long_flip_reverses_longs() -> None:
    d = _run_daily_signal(get_rule_fn=lambda _: _stub_rule("long_flip_oc", "override"))

    assert d["strategy_decision"]["selected_strategy"] == "long_flip_oc"
    # LONG が反転して SHORT になるため execution_plan.long は空
    assert d["execution_plan"]["long"] == []
    # SHORT は元 SHORT + 反転 LONG で増えている
    assert len(d["execution_plan"]["short"]) > 0
    assert d["adopted_long_count"] == 0


# ---------------------------------------------------------------------------
# 3. strategy_decision.selected_strategy と DailySignalResult.selected_strategy が一致
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("strategy", ["curr_oc", "skip", "long_flip_oc", "short_only_oc"])
def test_selected_strategy_consistency(strategy: str) -> None:
    d = _run_daily_signal(get_rule_fn=lambda _, s=strategy: _stub_rule(s))
    assert d["strategy_decision"]["selected_strategy"] == d["selected_strategy"], (
        f"strategy={strategy}: decision={d['strategy_decision']['selected_strategy']} "
        f"!= result={d['selected_strategy']}"
    )


# ---------------------------------------------------------------------------
# 4. pick_overnight_gap: execution_target_jp_date 行優先 + フォールバック
# ---------------------------------------------------------------------------

class TestPickOvernightGap:
    """juslag.services.daily_signal.pick_overnight_gap の単体テスト。"""

    def _make_df(self) -> pd.DataFrame:
        dates = pd.to_datetime(["2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16"])
        return pd.DataFrame(
            {
                "1617.T": [0.00, 0.01, 0.03, 0.005],
                "1618.T": [0.00, 0.01, 0.03, 0.005],
            },
            index=dates,
        )

    def test_exec_date_in_index_returns_that_row(self):
        df = self._make_df()
        exec_date = pd.Timestamp("2026-01-16")
        result = pick_overnight_gap(df, exec_date)
        pd.testing.assert_series_equal(result, df.loc[exec_date])

    def test_exec_date_not_in_index_returns_last_row(self):
        df = self._make_df()
        exec_date = pd.Timestamp("2026-01-20")  # index にない
        result = pick_overnight_gap(df, exec_date)
        pd.testing.assert_series_equal(result, df.iloc[-1])

    def test_none_exec_date_returns_last_row(self):
        df = self._make_df()
        result = pick_overnight_gap(df, None)
        pd.testing.assert_series_equal(result, df.iloc[-1])

    def test_empty_df_returns_empty_series(self):
        result = pick_overnight_gap(pd.DataFrame(), None)
        assert result.empty

    def test_exec_date_differs_from_iloc_minus1(self):
        """exec_date の行と iloc[-1] が別行の場合に正しく exec_date 行を返す。"""
        df = self._make_df()
        exec_date = pd.Timestamp("2026-01-14")  # iloc[-1] は 2026-01-16
        result = pick_overnight_gap(df, exec_date)
        pd.testing.assert_series_equal(result, df.loc[exec_date])
        assert not result.equals(df.iloc[-1])


# ---------------------------------------------------------------------------
# 5. pick_overnight_gap_fn に execution_target_jp_date が渡されることを確認
# ---------------------------------------------------------------------------

def test_pick_overnight_gap_called_with_execution_target_jp_date() -> None:
    """pick_overnight_gap_fn に execution_target_jp_date が渡されること。"""
    captured = {}

    def _tracking(df, exec_date):
        captured["exec_date"] = exec_date
        return pick_overnight_gap(df, exec_date)

    d = _run_daily_signal(pick_overnight_gap_fn=_tracking)

    assert "exec_date" in captured
    resp_date = d.get("execution_target_jp_date")
    if resp_date and captured["exec_date"] is not None:
        assert str(captured["exec_date"].date()) == resp_date


def test_strategy_context_open_gap_uses_pick_overnight_gap_result() -> None:
    """strategy_context.open_gap は pick_overnight_gap_fn の返り値の平均になること。"""
    fixed_gap = 0.025
    jp_tickers_in_test = [
        "1617.T", "1618.T", "1619.T", "1620.T", "1621.T",
        "1622.T", "1623.T", "1624.T", "1625.T",
    ]

    def _fake_pick(df, exec_date):
        return pd.Series({t: fixed_gap for t in jp_tickers_in_test})

    d = _run_daily_signal(pick_overnight_gap_fn=_fake_pick)
    assert abs(d["strategy_context"]["open_gap"] - fixed_gap) < 1e-6


# ---------------------------------------------------------------------------
# 6. pre_rule / post_rule 件数 + no_trade_classification 優先順位テスト
# ---------------------------------------------------------------------------

class TestPreRulePostRuleClassification:
    """strategy_rule skip 時の分類判定が apply前の値を正しく使うことを確認。"""

    def _get(self, strategy: str = "skip", action: str = "skip") -> dict:
        return _run_daily_signal(get_rule_fn=lambda _: _stub_rule(strategy, action))

    def test_skip_with_candidates_classification(self):
        """候補あり + skip → strategy_rule_skip_with_candidates。"""
        d = self._get("skip", "skip")

        assert d["trade_block_reason"] == "strategy_rule_skip"
        assert d["no_trade_classification"] == "strategy_rule_skip_with_candidates"
        assert d["strategy_rule_skip_has_candidates"] is True

    def test_pre_rule_counts_reflect_signal(self):
        """pre_rule_adopted_long/short_count は apply前の候補件数を返す。"""
        d = self._get("skip", "skip")

        # _fake_generate_signals は q=0.3 で 9 tickers → 各 3 件が LONG/SHORT
        assert d["pre_rule_adopted_long_count"] >= 1
        assert d["pre_rule_adopted_short_count"] >= 1

    def test_post_rule_counts_zero_for_skip(self):
        """post_rule_adopted_long/short_count は skip 後に 0 になる。"""
        d = self._get("skip", "skip")

        assert d["post_rule_adopted_long_count"] == 0
        assert d["post_rule_adopted_short_count"] == 0

    def test_signal_no_trade_classification_is_none_when_both_candidates_exist(self):
        """元シグナルで両側候補あり → signal_no_trade_classification は None。"""
        d = self._get("skip", "skip")

        assert d["signal_no_trade_classification"] is None

    def test_tradeable_false_and_no_execution_plan(self):
        """skip 時: tradeable=False かつ execution_plan が空。"""
        d = self._get("skip", "skip")

        assert d["tradeable"] is False
        assert d["execution_plan"]["long"] == []
        assert d["execution_plan"]["short"] == []

    def test_non_skip_preserves_signal_classification(self):
        """skip でない場合は signal ベースの分類を維持する。"""
        d = self._get("curr_oc", "execute")

        # 候補が揃う → no_trade_classification は None（tradeable）
        assert d["strategy_rule_skip_has_candidates"] is False
        assert d["no_trade_classification"] == d["signal_no_trade_classification"]

    def test_pre_post_counts_equal_for_non_skip(self):
        """skip でない場合: pre == post の adopted 件数。"""
        d = self._get("curr_oc", "execute")

        assert d["pre_rule_adopted_long_count"] == d["post_rule_adopted_long_count"]
        assert d["pre_rule_adopted_short_count"] == d["post_rule_adopted_short_count"]

    def test_near_miss_not_shown_when_strategy_skips(self):
        """strategy skip 時は near_miss_threshold が主分類にならない。"""
        d = self._get("skip", "skip")

        assert d["no_trade_classification"] != "near_miss_threshold"
        assert d["no_trade_classification"] != "hard_no_signal"
        assert d["no_trade_classification"] != "one_side_only"

    def test_existing_skip_test_still_passes(self):
        """既存テスト: skip → execution_plan 空 + adopted_long/short_count = 0。"""
        d = self._get("skip", "skip")

        assert d["strategy_decision"]["action"] == "skip"
        assert d["strategy_decision"]["selected_strategy"] == "skip"
        assert d["execution_plan"]["long"] == []
        assert d["execution_plan"]["short"] == []
        assert d["adopted_long_count"] == 0
        assert d["adopted_short_count"] == 0
        assert d["tradeable"] is False
        assert d["trade_block_reason"] == "strategy_rule_skip"
