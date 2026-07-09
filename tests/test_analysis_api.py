"""
build_data_status / evaluate_adjusted_series_verification / enrich_report_with_factor_analysis /
run_fetch_all のサービス層・ライブラリ層カバレッジ。

旧 webui HTTP エンドポイントのアサーションは削除し、下層のライブラリ関数を直接検証する。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from juslag.analysis_report import enrich_report_with_factor_analysis
from juslag.cache import PriceCache
from juslag.config import AppConfig
from juslag.services.backtest import BacktestParams
from juslag.services.daily_signal import run_daily_signal_service
from juslag.services.data_status import (
    MIN_ACTIONS_COVERAGE_RATIO,
    MIN_ACTIONS_EVENT_COUNT,
    build_data_status,
    evaluate_adjusted_series_verification,
)
from juslag.services.fetch_all import run_fetch_all


def test_data_status_has_readiness(tmp_path: Path) -> None:
    cache = PriceCache()
    cfg = AppConfig()
    d = build_data_status(
        cache,
        cfg,
        external_dir=tmp_path / "external",
        report_path=tmp_path / "juslag_report.json",
    )
    assert "factor_data" in d
    assert "corporate_actions" in d
    assert "analysis_readiness" in d


def test_backtest_request_defaults_match_app_config() -> None:
    cfg = AppConfig()
    req = BacktestParams()
    assert req.sample_start == cfg.paper_like.sample_start
    assert req.sample_end == (cfg.paper_like.sample_end or "")
    assert req.pretrain_end == cfg.paper_like.pretrain_end
    assert req.window_l == cfg.strategy.window_l
    assert req.k_factors == cfg.strategy.k_factors
    assert req.lambda_reg == cfg.strategy.lambda_reg


def test_enrich_report_with_factor_analysis_unavailable(tmp_path: Path) -> None:
    """factor データが無い場合: available=False, regression_status に reason が入る。"""
    payload = enrich_report_with_factor_analysis({"rows": []}, tmp_path / "external")
    assert payload["factor_source"]["available"] is False
    assert payload["factor_regression_status"]["ready"] is False
    assert payload["factor_regression_status"]["reason"] == "factor_data_unavailable"
    assert payload["factor_regression"] == {"ff3": None, "carhart4": None}


def test_data_status_includes_actions_detail_fields(tmp_path: Path) -> None:
    cache = PriceCache()
    cfg = AppConfig()
    d = build_data_status(
        cache,
        cfg,
        external_dir=tmp_path / "external",
        report_path=tmp_path / "juslag_report.json",
    )
    for k in [
        "actions_coverage_ratio", "actions_tickers_covered", "actions_start", "actions_end",
        "adjusted_series_verification_reason", "factor_regression_reason",
        "factor_regression_n_obs", "paper_reproduction_reason",
    ]:
        assert k in d


def test_adjusted_series_verified_not_simple_available() -> None:
    verified, reason, detail = evaluate_adjusted_series_verification(
        {
            "available": True,
            "tickers_covered": ["A"],
            "total": 1,
            "dividends": 0,
            "splits": 0,
            "start": "2025-01-01",
            "end": "2025-12-31",
        },
        expected_tickers=28,
        required_start="2026-01-01",
        required_end="2026-04-01",
    )
    assert verified is False
    assert reason in {
        "coverage_ratio_below_threshold", "required_range_not_covered",
        "insufficient_actions_events", "no_dividends_or_splits", "missing_date_range",
    }
    assert detail["coverage_ratio"] < 0.6


def test_paper_reproduction_ready_requires_all_conditions(tmp_path: Path) -> None:
    """paper_reproduction_ready は factor_data_ready + factor_regression_ready + adjusted_verification + report すべて必要。"""
    cache = PriceCache()
    cfg = AppConfig()
    d = build_data_status(
        cache,
        cfg,
        external_dir=tmp_path / "external",
        report_path=tmp_path / "juslag_report.json",
    )
    factor_ready = bool(d.get("analysis_readiness", {}).get("factor_data_ready"))
    factor_reg_ready = bool(d.get("factor_regression_ready"))
    adj_verified = bool(d.get("adjusted_series_verified"))
    report_available = (tmp_path / "juslag_report.json").exists()
    expected = factor_ready and factor_reg_ready and adj_verified and report_available
    assert bool(d.get("paper_reproduction_ready")) == expected, (
        f"paper_reproduction_ready mismatch: expected={expected}, got={d.get('paper_reproduction_ready')}"
    )
    assert "paper_reproduction_reason" in d


def test_adjusted_series_verification_checks_range_and_events() -> None:
    """start/end/coverage/event count を見て判定される。"""
    v1, rc1, detail1 = evaluate_adjusted_series_verification(
        {
            "available": True,
            "tickers_covered": list(range(20)),
            "total": 100,
            "dividends": 10,
            "splits": 5,
            "start": "2020-01-01",
            "end": "2022-12-31",
        },
        expected_tickers=20,
        required_start="2010-01-01",
        required_end="2022-12-31",
    )
    assert v1 is False
    assert rc1 == "required_range_not_covered"
    assert detail1["required_range_covered"] is False

    v2, rc2, _ = evaluate_adjusted_series_verification(
        {
            "available": True,
            "tickers_covered": list(range(20)),
            "total": 100,
            "dividends": 0,
            "splits": 0,
            "start": "2010-01-01",
            "end": "2026-12-31",
        },
        expected_tickers=20,
        required_start="2010-01-01",
        required_end="2026-12-31",
    )
    assert v2 is False
    assert rc2 == "no_dividends_or_splits"

    v3, rc3, d3 = evaluate_adjusted_series_verification(
        {
            "available": True,
            "tickers_covered": list(range(20)),
            "total": 100,
            "dividends": 50,
            "splits": 10,
            "start": "2010-01-01",
            "end": "2026-12-31",
        },
        expected_tickers=20,
        required_start="2010-01-01",
        required_end="2026-12-31",
    )
    assert v3 is True
    assert rc3 == "ok"
    assert d3["coverage_ratio"] == 1.0


def test_min_actions_constants_defined() -> None:
    assert MIN_ACTIONS_COVERAGE_RATIO == 0.6
    assert MIN_ACTIONS_EVENT_COUNT == 10


def test_daily_signal_generate_signals_called_once() -> None:
    calls = {"n": 0}

    def _fake_generate_signals(*args, **kwargs):
        calls["n"] += 1
        idx = pd.to_datetime(["2026-07-07"])
        return pd.DataFrame({"1617.T": [0.1], "1625.T": [-0.1]}, index=idx)

    from datetime import datetime
    from zoneinfo import ZoneInfo

    now_jst = datetime(2026, 7, 8, 8, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    run_daily_signal_service(
        AppConfig(),
        PriceCache(),
        operation_mode="development",
        now_jst=now_jst,
        generate_signals_fn=_fake_generate_signals,
    )
    assert calls["n"] == 1


def test_run_fetch_all_reports_data_status_refresh_step() -> None:
    """price/factor/actions を全てスキップした場合でも data_status_refresh ステップは実行される（オフライン）。"""
    cache = PriceCache()
    result = run_fetch_all(
        "2010-01-01",
        "2026-12-31",
        price_modes=[],
        include_factors=False,
        include_actions=False,
        project_root=Path("."),
        cache=cache,
    )
    assert result["status"] == "ok"
    assert set(result["steps"].keys()) == {"data_status_refresh"}
    assert result["steps"]["data_status_refresh"]["status"] == "ok"
