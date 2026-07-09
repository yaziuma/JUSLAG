from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from juslag.services.notify import build_slack_summary

_JST = ZoneInfo("Asia/Tokyo")


def _fixture_bt() -> dict:
    return {
        "judge": {"overall_score": 82, "overall_decision": "pass"},
        "performance_sets": {
            "net_after_tax": [{"AR(%)": 12.34, "R/R": 1.2, "MDD(%)": -8.5}],
        },
    }


def _base_ds(**overrides) -> dict:
    ds = {
        "execution_target_jp_date": "2026-07-09",
        "signal_reference_us_date": "2026-07-08",
        "tradeable": True,
        "trade_block_reason": None,
        "execution_plan": {
            "long": [{"ticker": "1625.T", "sector": "電機・精密"}],
            "short": [{"ticker": "1630.T", "sector": "小売"}],
        },
        "trend_regime": "uptrend",
        "vol_regime": "normal",
        "strategy_context": {"rotation_regime": "rotating", "open_gap": 0.0012},
        "no_trade_classification": None,
        "candidate_signal_strength": 0.15,
        "adopted_signal_strength": 0.10,
        "candidate_signal_stats": {},
        "rows": [{"ticker": "1625.T", "signal": 0.15}],
    }
    ds.update(overrides)
    return ds


def test_build_slack_summary_includes_judge_score_and_regime_line() -> None:
    now_jst = datetime(2026, 7, 8, 8, 0, tzinfo=_JST)
    text = build_slack_summary(_fixture_bt(), _base_ds(), now_jst)

    assert "82" in text
    assert "pass" in text
    assert "Regime: uptrend / normal / rotation=rotating" in text


def test_build_slack_summary_includes_strategy_rule_detail_on_skip() -> None:
    now_jst = datetime(2026, 7, 8, 8, 0, tzinfo=_JST)
    ds = _base_ds(
        tradeable=False,
        trade_block_reason="strategy_rule_skip",
        pre_rule_adopted_long_count=1,
        pre_rule_adopted_short_count=1,
        post_rule_adopted_long_count=0,
        post_rule_adopted_short_count=0,
        strategy_decision={
            "rule_id": "rule_406_no_flip",
            "rule_name_ja": "406番ルール（フリップなし）",
            "action": "skip",
            "reason_ja": "ローテーション局面での反転条件に合致したため見送り",
            "matched_filter": "rotation_and_high_vol",
        },
    )
    text = build_slack_summary(_fixture_bt(), ds, now_jst)

    assert "406番ルール（フリップなし）" in text
    assert "ローテーション局面での反転条件に合致したため見送り" in text
    assert "rotation_and_high_vol" in text
