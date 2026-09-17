from __future__ import annotations

import math

from juslag.services.backtest import BacktestParams


def _to_jsonable(value: object) -> object:
    """Recursively normalize a value into something json.dumps can handle.

    - float NaN/inf -> None
    - numpy scalar types -> plain python (via .item() when available)
    - pandas Timestamp/NaT and other objects with isoformat() -> str
    - dict/list/tuple -> recursed
    """
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    # numpy scalars (e.g. numpy.float64, numpy.int64, numpy.bool_) expose .item()
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _to_jsonable(item())
        except (ValueError, TypeError):
            pass
    # pandas Timestamp / NaT and similar objects expose isoformat()
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except (ValueError, TypeError):
            pass
    # pandas NaT / numpy nan-likes: fall back to isna check
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except (ImportError, TypeError, ValueError):
        pass
    return str(value)


def build_daily_report(
    date: str,
    bt: dict,
    ds: dict,
    fetch_result: dict,
    params: BacktestParams,
    settings_name: str,
    history_entry: dict,
    slack_fallback_text: str,
    generated_at_utc: str,
    paper_bt: dict | None = None,
    paper_params: BacktestParams | None = None,
) -> dict:
    fetch_steps = {}
    for name, step in (fetch_result.get("steps") or {}).items():
        fetch_steps[name] = {k: v for k, v in step.items() if k != "log"}

    history_entry_clean = {k: v for k, v in history_entry.items() if k != "raw_signal_json"}

    report = {
        "schema_version": 1,
        "date": date,
        "generated_at_utc": generated_at_utc,
        "backtest": {
            "settings_name": settings_name,
            "judge_strategy_name": bt.get("judge_strategy_name"),
            "params": params.model_dump(),
            "judge": bt.get("judge"),
            "performance_sets": bt.get("performance_sets"),
            "cost_breakdown": bt.get("cost_breakdown"),
            "eval_start": bt.get("eval_start"),
        },
        "daily_signal": ds,
        "fetch": {
            "status": fetch_result.get("status"),
            "error_summary": fetch_result.get("error_summary"),
            "steps": fetch_steps,
        },
        "history_entry": history_entry_clean,
        "slack_fallback_text": slack_fallback_text,
    }
    if paper_bt is not None and paper_params is not None:
        report["backtest_comparison"] = {
            "current": _comparison_entry(
                "現行運用",
                bt,
                params,
                "本番設定。論文外のメタルールとシグナル閾値を含む。",
            ),
            "paper_aligned": _comparison_entry(
                "論文準拠",
                paper_bt,
                paper_params,
                "調整済み価格、PCA SUB単体、上下30%等ウェイト。期間とデータ供給元は実装準拠。",
            ),
            "shared_cost_assumptions": {
                "commission_bps_per_side": params.commission_bps_per_side,
                "slippage_bps_per_side": params.slippage_bps_per_side,
                "short_borrow_rate_annual": params.short_borrow_rate_annual,
                "tax_enabled": params.tax_enabled,
                "tax_rate": params.tax_rate,
                "tax_model": params.tax_model,
            },
        }
    return _to_jsonable(report)


def _comparison_entry(label: str, bt: dict, params: BacktestParams, note: str) -> dict:
    judge = bt.get("judge") or {}
    return {
        "label": label,
        "strategy_name": bt.get("judge_strategy_name"),
        "note": note,
        "price_mode": params.price_mode,
        "sample_start": params.sample_start,
        "sample_end": params.sample_end,
        "eval_start": bt.get("eval_start"),
        "strategy_rule_id": params.strategy_rule_id,
        "same_open_gap_assumption": bool(params.strategy_rule_id),
        "judge": {
            "overall_score": judge.get("overall_score"),
            "overall_decision": judge.get("overall_decision"),
        },
        "metrics": judge.get("metrics_snapshot") or {},
        "cost_breakdown": bt.get("cost_breakdown") or {},
    }
