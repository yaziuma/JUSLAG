from __future__ import annotations

import json
import math

from juslag.services.backtest import BacktestParams
from juslag.services.daily_report import build_daily_report


def _fixture_bt() -> dict:
    return {
        "judge_strategy_name": "PCA SUB + rule_406_no_flip",
        "judge": {"overall_score": 82, "overall_decision": "pass"},
        "performance_sets": {
            "net_after_tax": [{"AR(%)": 12.3, "R/R": 1.2, "MDD(%)": -8.5}],
        },
        "cost_breakdown": {"commission_total": 1.0, "slippage_total": float("nan")},
        "eval_start": "2022-01-01",
    }


def _fixture_ds() -> dict:
    return {
        "tradeable": True,
        "trade_block_reason": None,
        "execution_plan": {
            "long": [{"ticker": "1625.T", "sector": "電機・精密"}],
            "short": [{"ticker": "1630.T", "sector": "小売"}],
            "n_long": 1,
            "n_short": 1,
        },
        "trend_regime": "uptrend",
        "vol_regime": "normal",
        "rows": [{"ticker": "1625.T", "signal": 0.12}],
    }


def _fixture_fetch_result() -> dict:
    return {
        "status": "ok",
        "error_summary": [],
        "steps": {
            "price_raw": {"name": "price_raw", "status": "ok", "updated_at": 123.0},
            "factors": {
                "name": "factors",
                "status": "ok",
                "updated_at": 124.0,
                "log": "a very long subprocess log that should be dropped",
            },
        },
    }


def _fixture_history_entry() -> dict:
    return {
        "dedupe_key": "dk-1",
        "cached_date": "2026-07-08",
        "tradeable": True,
        "long_tickers": ["1625.T"],
        "raw_signal_json": json.dumps({"huge": "payload"}),
    }


def test_build_daily_report_schema_and_shape() -> None:
    params = BacktestParams()
    report = build_daily_report(
        date="2026-07-08",
        bt=_fixture_bt(),
        ds=_fixture_ds(),
        fetch_result=_fixture_fetch_result(),
        params=params,
        settings_name="本番適用 test",
        history_entry=_fixture_history_entry(),
        slack_fallback_text="fallback text",
        generated_at_utc="2026-07-08T00:00:00+00:00",
    )

    assert report["schema_version"] == 1
    assert report["date"] == "2026-07-08"
    assert report["generated_at_utc"] == "2026-07-08T00:00:00+00:00"

    assert report["backtest"]["settings_name"] == "本番適用 test"
    assert report["backtest"]["judge_strategy_name"] == "PCA SUB + rule_406_no_flip"
    assert report["backtest"]["params"] == params.model_dump()
    assert report["backtest"]["judge"]["overall_score"] == 82
    assert report["backtest"]["performance_sets"]["net_after_tax"][0]["AR(%)"] == 12.3
    assert report["backtest"]["eval_start"] == "2022-01-01"

    assert report["daily_signal"]["tradeable"] is True

    assert report["fetch"]["status"] == "ok"
    assert report["fetch"]["error_summary"] == []
    for step in report["fetch"]["steps"].values():
        assert "log" not in step
    assert report["fetch"]["steps"]["factors"]["status"] == "ok"

    assert "raw_signal_json" not in report["history_entry"]
    assert report["history_entry"]["dedupe_key"] == "dk-1"

    assert report["slack_fallback_text"] == "fallback text"


def test_build_daily_report_normalizes_nan_to_none_and_is_json_dumpable() -> None:
    params = BacktestParams()
    report = build_daily_report(
        date="2026-07-08",
        bt=_fixture_bt(),
        ds=_fixture_ds(),
        fetch_result=_fixture_fetch_result(),
        params=params,
        settings_name="本番適用 test",
        history_entry=_fixture_history_entry(),
        slack_fallback_text="fallback text",
        generated_at_utc="2026-07-08T00:00:00+00:00",
    )

    assert report["backtest"]["cost_breakdown"]["slippage_total"] is None

    text = json.dumps(report, ensure_ascii=False)
    round_tripped = json.loads(text)
    assert round_tripped["schema_version"] == 1
    assert round_tripped["backtest"]["cost_breakdown"]["slippage_total"] is None

    def _no_nan(value: object) -> bool:
        if isinstance(value, float):
            return not math.isnan(value)
        if isinstance(value, dict):
            return all(_no_nan(v) for v in value.values())
        if isinstance(value, list):
            return all(_no_nan(v) for v in value)
        return True

    assert _no_nan(report)


def test_build_daily_report_includes_comparable_paper_backtest() -> None:
    params = BacktestParams(strategy_rule_id="rule_406_no_flip", price_mode="raw")
    paper_params = params.model_copy(
        update={
            "strategy_rule_id": None,
            "price_mode": "adjusted",
            "min_long_signal": -1.0e9,
            "max_short_signal": 1.0e9,
        }
    )
    paper_bt = {
        **_fixture_bt(),
        "judge_strategy_name": "PCA SUB",
        "judge": {
            "overall_score": 71,
            "overall_decision": "warn",
            "metrics_snapshot": {"net_after_tax_ar_pct": 4.2},
        },
    }

    report = build_daily_report(
        date="2026-07-08",
        bt=_fixture_bt(),
        ds=_fixture_ds(),
        fetch_result=_fixture_fetch_result(),
        params=params,
        settings_name="本番適用 test",
        history_entry=_fixture_history_entry(),
        slack_fallback_text="fallback text",
        generated_at_utc="2026-07-08T00:00:00+00:00",
        paper_bt=paper_bt,
        paper_params=paper_params,
    )

    comparison = report["backtest_comparison"]
    assert comparison["current"]["strategy_name"] == "PCA SUB + rule_406_no_flip"
    assert comparison["paper_aligned"]["strategy_name"] == "PCA SUB"
    assert comparison["paper_aligned"]["price_mode"] == "adjusted"
    assert comparison["paper_aligned"]["strategy_rule_id"] is None
    assert comparison["paper_aligned"]["metrics"]["net_after_tax_ar_pct"] == 4.2
    assert comparison["shared_cost_assumptions"]["slippage_bps_per_side"] == params.slippage_bps_per_side
