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
    return _to_jsonable(report)
