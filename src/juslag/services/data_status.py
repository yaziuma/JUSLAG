from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from juslag.cache import PriceCache
from juslag.config import AppConfig, JP_TICKERS, US_TICKERS
from juslag.factor_analysis import evaluate_factor_regression_readiness, load_factor_frame

MIN_ACTIONS_COVERAGE_RATIO = 0.6
MIN_ACTIONS_EVENT_COUNT = 10


def evaluate_adjusted_series_verification(
    actions: dict,
    expected_tickers: int,
    required_start: str | None = None,
    required_end: str | None = None,
) -> tuple[bool, str, dict[str, object]]:
    covered = actions.get("tickers_covered") or []
    coverage_ratio = float(len(covered)) / float(expected_tickers) if expected_tickers else 0.0
    total = int(actions.get("total") or 0)
    dividends = int(actions.get("dividends") or 0)
    splits = int(actions.get("splits") or 0)
    actions_start = actions.get("start")
    actions_end = actions.get("end")
    has_date_range = bool(actions_start and actions_end)
    required_range_specified = bool(required_start and required_end)
    min_actions_events = max(MIN_ACTIONS_EVENT_COUNT, int(expected_tickers * 0.2))
    enough_events = total >= min_actions_events
    enough_coverage = coverage_ratio >= MIN_ACTIONS_COVERAGE_RATIO
    has_event_types = dividends > 0 or splits > 0

    reason_code = "ok"
    covers_required_range = True
    if not bool(actions.get("available")):
        reason_code = "actions_data_unavailable"
    elif not has_date_range:
        reason_code = "missing_date_range"
    elif required_range_specified and not (actions_start <= required_start and actions_end >= required_end):
        covers_required_range = False
        reason_code = "required_range_not_covered"
    elif not enough_coverage:
        reason_code = "coverage_ratio_below_threshold"
    elif not enough_events:
        reason_code = "insufficient_actions_events"
    elif not has_event_types:
        reason_code = "no_dividends_or_splits"

    verified = reason_code == "ok"
    detail = {
        "reason_code": reason_code,
        "coverage_ratio": coverage_ratio,
        "tickers_covered": len(covered),
        "actions_total": total,
        "actions_start": actions_start,
        "actions_end": actions_end,
        "required_start": required_start,
        "required_end": required_end,
        "required_range_specified": required_range_specified,
        "required_range_covered": covers_required_range,
        "min_actions_events": min_actions_events,
        "min_actions_coverage_ratio": MIN_ACTIONS_COVERAGE_RATIO,
    }
    return verified, reason_code, detail


def build_data_status(
    cache: PriceCache,
    cfg: AppConfig,
    external_dir: Path = Path("data/external"),
    report_path: Path = Path("outputs/juslag_report.json"),
) -> dict:
    """ファクターデータ・コーポレートアクションの取得状況を返す"""
    base = external_dir

    def _factor_status() -> dict:
        factor_df, factor_source = load_factor_frame(base)
        if factor_df.empty:
            return {"available": False}
        start = factor_df.index.min()
        end = factor_df.index.max()
        return {
            "available": True,
            "model": "Carhart4" if "WML" in factor_df.columns else "FF3",
            "rows": int(len(factor_df)),
            "start": start.date().isoformat() if pd.notna(start) else None,
            "end": end.date().isoformat() if pd.notna(end) else None,
            "updated_at": None,
            "source": str(factor_source) if factor_source else None,
        }

    def _actions_status() -> dict:
        meta_path = base / "actions" / "normalized" / "actions_metadata.json"
        if not meta_path.exists():
            return {"available": False}
        m = json.loads(meta_path.read_text())
        covered = m.get("tickers_covered") or m.get("covered_tickers") or []
        coverage_ratio = float(len(covered)) / float(len(US_TICKERS) + len(JP_TICKERS)) if (len(US_TICKERS) + len(JP_TICKERS)) else 0.0
        return {
            "available": True,
            "dividends": m.get("dividends"),
            "splits": m.get("splits"),
            "total": m.get("total_actions"),
            "updated_at": m.get("updated_at"),
            "start": m.get("start"),
            "end": m.get("end"),
            "tickers_covered": covered,
            "coverage_ratio": coverage_ratio,
        }

    factor = _factor_status()
    actions = _actions_status()
    raw_summary = cache.summary(list(US_TICKERS.keys()), list(JP_TICKERS.keys()), price_mode="raw")
    adjusted_summary = cache.summary(list(US_TICKERS.keys()), list(JP_TICKERS.keys()), price_mode="adjusted")
    expected_tickers = len(US_TICKERS) + len(JP_TICKERS)
    required_start = cfg.paper_like.sample_start
    required_end = cfg.paper_like.sample_end or raw_summary.get("required_latest_date")
    adjusted_verified, adjusted_reason, adjusted_detail = evaluate_adjusted_series_verification(
        actions,
        expected_tickers,
        required_start=required_start,
        required_end=required_end,
    )
    actions_cov = float(adjusted_detail.get("coverage_ratio") or 0.0)
    report_available = report_path.exists()
    strategy_returns = pd.Series(dtype=float)
    if report_available:
        try:
            report_payload = json.loads(report_path.read_text())
            rows = report_payload.get("rows") or []
            if rows:
                perf = pd.DataFrame(rows)
                if "date" in perf.columns and "ret_sub" in perf.columns:
                    perf["date"] = pd.to_datetime(perf["date"])
                    strategy_returns = perf.set_index("date").sort_index()["ret_sub"].dropna()
        except Exception:
            strategy_returns = pd.Series(dtype=float)
    factor_df, _ = load_factor_frame(base)
    factor_readiness = evaluate_factor_regression_readiness(factor_df, strategy_returns)
    factor_regression_ready = bool(factor_readiness.get("ready"))

    factor_data_ready = bool(factor.get("available"))
    adjusted_verification_ready = bool(adjusted_verified)
    paper_ready_conditions = {
        "factor_data_ready": factor_data_ready,
        "factor_regression_ready": factor_regression_ready,
        "adjusted_verification_ready": adjusted_verification_ready,
        "report_available": report_available,
    }
    paper_reproduction_ready = all(paper_ready_conditions.values())
    paper_reproduction_reason = "ok" if paper_reproduction_ready else "missing_requirements:" + ",".join([k for k, v in paper_ready_conditions.items() if not v])
    return {
        "price_cache": {"raw": raw_summary, "adjusted": adjusted_summary},
        "factor_data": factor,
        "corporate_actions": actions,
        "analysis_readiness": {
            "price_cache_ready": bool(raw_summary.get("daily_signal_ready")),
            "daily_signal_ready": bool(raw_summary.get("daily_signal_ready")),
            "factor_data_ready": factor_data_ready,
            "actions_data_ready": bool(actions.get("available")),
            "factor_regression_ready": factor_regression_ready,
            "adjusted_verification_ready": adjusted_verification_ready,
            "paper_reproduction_ready": paper_reproduction_ready,
        },
        "adjusted_series_verified": adjusted_verified,
        "paper_reproduction_ready": paper_reproduction_ready,
        "paper_reproduction_reason": paper_reproduction_reason,
        "factor_regression_ready": factor_regression_ready,
        "factor_regression_reason": factor_readiness.get("reason"),
        "factor_regression_n_obs": factor_readiness.get("n_obs", 0),
        "factor_regression_start": factor_readiness.get("start"),
        "factor_regression_end": factor_readiness.get("end"),
        "actions_coverage_ratio": actions_cov,
        "actions_tickers_covered": len(actions.get("tickers_covered") or []),
        "actions_start": actions.get("start"),
        "actions_end": actions.get("end"),
        "adjusted_series_verification_reason": adjusted_reason if not adjusted_verified else None,
        "adjusted_series_verification_reason_code": adjusted_reason,
        "adjusted_series_warning": None if adjusted_verified else f"adjusted verification failed: {adjusted_reason}",
        "report": {"available": report_available},
    }
