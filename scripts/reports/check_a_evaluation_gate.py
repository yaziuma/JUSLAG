"""Report A1-A3 frozen-gate readiness without changing the acceptance criteria."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pandas_market_calendars as mcal
import yaml

from juslag.config import JP_TICKERS
from juslag.intraday import load_intraday_bars


def evaluate_proxy(bars: pd.DataFrame, gate: dict) -> dict:
    cfg = gate["a2"]["proxy_collection"]
    if bars.empty:
        return {"observed_sessions": 0, "complete_sessions": 0, "ready": False}
    frame = bars.copy()
    frame["bar_jst"] = pd.to_datetime(frame["bar_start_utc"], utc=True).dt.tz_convert("Asia/Tokyo")
    frame["observed_utc"] = pd.to_datetime(frame["observed_at_utc"], utc=True)
    frame["session"] = frame["bar_jst"].dt.strftime("%Y-%m-%d")
    frame["clock"] = frame["bar_jst"].dt.strftime("%H:%M")
    frame["delay_minutes"] = (frame["observed_utc"] - frame["bar_jst"].dt.tz_convert("UTC")).dt.total_seconds() / 60
    frame = frame[frame["session"] >= cfg["start_jp_session"]]
    eligible = frame[
        (frame["clock"] >= cfg["postopen_bar_start_minute"])
        & (frame["clock"] <= cfg["postopen_bar_end_minute"])
        & (frame["delay_minutes"] <= cfg["maximum_observation_delay_minutes"])
    ]
    observed_sessions = sorted(frame["session"].unique())
    coverage = (eligible.groupby("session")["ticker"].nunique() / len(JP_TICKERS)).reindex(observed_sessions, fill_value=0)
    complete = coverage[coverage >= cfg["required_ticker_day_coverage"]]
    return {
        "observed_sessions": len(observed_sessions),
        "complete_sessions": len(complete),
        "minimum_complete_sessions": cfg["minimum_complete_sessions"],
        "latest_session": max(observed_sessions) if observed_sessions else None,
        "median_ticker_coverage": round(float(coverage.median()), 4) if len(coverage) else 0.0,
        "ready": len(complete) >= cfg["minimum_complete_sessions"],
    }


def evaluate_holdout(gate: dict, as_of: str) -> dict:
    cfg = gate["a3"]["prospective_holdout"]
    schedule = mcal.get_calendar("JPX").schedule(cfg["start_jp_session"], cfg["end_jp_session"])
    completed = int((schedule.index <= pd.Timestamp(as_of)).sum())
    return {
        "start_jp_session": cfg["start_jp_session"],
        "end_jp_session": cfg["end_jp_session"],
        "expected_sessions": cfg["jp_sessions"],
        "calendar_sessions": len(schedule),
        "completed_sessions": completed,
        "ready": completed >= cfg["jp_sessions"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", type=Path, default=Path("config/a_evaluation_gate.yaml"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("data/opening_bars"))
    parser.add_argument("--as-of", default=pd.Timestamp.now(tz="Asia/Tokyo").date().isoformat())
    args = parser.parse_args()
    gate = yaml.safe_load(args.gate.read_text(encoding="utf-8"))
    bars = load_intraday_bars(snapshot_dir=args.snapshot_dir)
    result = {
        "decision": gate["decision"],
        "live_trading_allowed": gate["live_trading_allowed"],
        "a1": {"conclusion": gate["a1"]["conclusion"]},
        "a2_proxy": evaluate_proxy(bars, gate),
        "a2_go_requires_broker_execution_records": gate["a2"]["go_requires_broker_execution_records"],
        "a3_holdout": evaluate_holdout(gate, args.as_of),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
