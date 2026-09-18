"""Audit historical signal/input/execution dates from the local raw price cache."""
from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

import pandas as pd
import pandas_market_calendars as mcal

from juslag.cache import DEFAULT_DB_PATH, PriceCache
from juslag.config import JP_TICKERS, US_TICKERS
from juslag.data_loader import build_joint_cc, compute_returns, repair_known_bad_prices


def audit_dates(
    us_dates: pd.DatetimeIndex,
    jp_dates: pd.DatetimeIndex,
    *,
    pretrain_end: str,
    window: int,
    start: str = "2022-01-01",
    training_dates: pd.DatetimeIndex | None = None,
    us_close_times: dict[pd.Timestamp, pd.Timestamp] | None = None,
    jp_close_times: dict[pd.Timestamp, pd.Timestamp] | None = None,
    last_observed_at: dict[tuple[str, str], pd.Timestamp] | None = None,
) -> list[dict[str, str]]:
    """Use market-session dates; a row does not prove its publication timestamp."""
    us_dates = us_dates.sort_values().unique()
    jp_dates = jp_dates.sort_values().unique()
    common = us_dates.intersection(jp_dates) if training_dates is None else training_dates.sort_values().unique()
    if window < 1:
        raise ValueError("window must be positive")
    prior_end = pd.Timestamp(pretrain_end)
    rows: list[dict[str, str]] = []
    for signal_date in us_dates:
        if signal_date < pd.Timestamp(start):
            continue
        history = common[common < signal_date]
        if len(history) < window:
            continue
        jp_input_pos = jp_dates.searchsorted(signal_date, side="right") - 1
        execution_pos = jp_dates.searchsorted(signal_date, side="right")
        jp_input = jp_dates[jp_input_pos] if jp_input_pos >= 0 else pd.NaT
        execution = jp_dates[execution_pos] if execution_pos < len(jp_dates) else pd.NaT
        last_training = history[-1]
        date_order_ok = bool(
            pd.notna(jp_input)
            and pd.notna(execution)
            and prior_end < signal_date
            and last_training < signal_date
            and jp_input <= signal_date < execution
        )
        execution_day = execution.date().isoformat() if pd.notna(execution) else ""
        deadline = pd.Timestamp(f"{execution_day} 08:00", tz="Asia/Tokyo") if execution_day else pd.NaT
        us_close = us_close_times.get(signal_date) if us_close_times is not None else None
        jp_close = jp_close_times.get(jp_input) if jp_close_times is not None else None
        market_close_ok = (
            pd.notna(deadline) and us_close is not None and jp_close is not None
            and us_close < deadline and jp_close < deadline
        )
        input_observation = "not_recorded"
        latest_observed = None
        if last_observed_at is not None and pd.notna(jp_input) and pd.notna(deadline):
            required = [(ticker, signal_date.date().isoformat()) for ticker in US_TICKERS]
            required += [(ticker, jp_input.date().isoformat()) for ticker in JP_TICKERS]
            observed = [last_observed_at.get(key) for key in required]
            if all(value is not None for value in observed):
                latest_observed = max(observed)
                input_observation = (
                    "recorded_before_deadline" if latest_observed <= deadline
                    else "observed_after_deadline"
                )
        # The opening price is not observable by the 08:00 JST decision run.
        if signal_date not in common:
            audit_result = "not_historical_signal"
        elif not date_order_ok:
            audit_result = "blocked_date_order"
        else:
            audit_result = "blocked_gap_same_open_fill"
        rows.append({
            "signal_date": signal_date.date().isoformat(),
            "signal_path": "historical_joint_row" if signal_date in common else "not_historical_signal",
            "last_training_common_date": last_training.date().isoformat(),
            "last_us_input_date": signal_date.date().isoformat(),
            "last_jp_input_date": jp_input.date().isoformat() if pd.notna(jp_input) else "",
            "us_market_close_jst": us_close.isoformat() if us_close is not None else "",
            "jp_market_close_jst": jp_close.isoformat() if jp_close is not None else "",
            "decision_deadline_jst": f"{execution_day} 08:00 JST" if execution_day else "",
            "execution_jp_date": execution_day,
            "gap_observable_at": f"{execution_day} JP open or later" if execution_day else "",
            "assumed_fill_at": f"{execution_day} JP open" if execution_day else "",
            "date_order": "ok" if date_order_ok else "fail",
            "market_close_before_deadline": "yes" if market_close_ok else "unverified_or_no",
            "latest_input_observation_status": input_observation,
            "latest_input_observed_at_utc": latest_observed.tz_convert("UTC").isoformat() if latest_observed is not None else "",
            "price_publication_time": "unverified",
            "gap_after_open_fill": "unverified_same_open_assumption",
            "audit_result": audit_result,
        })
    return rows


def load_input_dates(db_path: Path, start: str, end: str, mode: str) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex, pd.DatetimeIndex]:
    cache = PriceCache(db_path)
    us = cache.load(list(US_TICKERS), start, end, mode)
    jp = cache.load(list(JP_TICKERS), start, end, mode)
    missing = (set(US_TICKERS) - us.keys()) | (set(JP_TICKERS) - jp.keys())
    if missing:
        raise ValueError(f"Missing cached tickers: {sorted(missing)}")
    us_close = pd.concat([us[t]["close"].rename(t) for t in US_TICKERS], axis=1)
    jp_close = pd.concat([jp[t]["close"].rename(t) for t in JP_TICKERS], axis=1)
    jp_open = pd.concat([jp[t]["open"].rename(t) for t in JP_TICKERS], axis=1)
    jp_open, jp_close = repair_known_bad_prices(jp_open, jp_close)
    us_cc, _, jp_cc = compute_returns(us_close, jp_close, jp_open)
    joint, _ = build_joint_cc(us_cc, jp_cc, fill_policy="strict", price_mode=mode)
    return us_close.dropna(how="all").index, jp_close.dropna(how="all").index, joint.index


def market_close_times(calendar_name: str, start: str, end: str) -> dict[pd.Timestamp, pd.Timestamp]:
    schedule = mcal.get_calendar(calendar_name).schedule(start_date=start, end_date=end)
    return {
        pd.Timestamp(day).tz_localize(None): close.tz_convert("Asia/Tokyo")
        for day, close in schedule["market_close"].items()
    }


def load_last_observations(db_path: Path, mode: str) -> dict[tuple[str, str], pd.Timestamp]:
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'price_observations'"
        ).fetchone()
        if not exists:
            return {}
        rows = conn.execute(
            "SELECT ticker, date, MAX(observed_at_utc) FROM price_observations "
            "WHERE price_mode = ? GROUP BY ticker, date",
            (mode,),
        ).fetchall()
    return {(ticker, day): pd.Timestamp(stamp) for ticker, day, stamp in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--end", default="2026-09-19", help="Exclusive YYYY-MM-DD")
    parser.add_argument("--pretrain-end", default="2021-12-31")
    parser.add_argument("--sample-start", default="2018-07-01")
    parser.add_argument("--mode", choices=("raw", "adjusted"), default="raw")
    parser.add_argument("--start", default="2022-01-01", help="Inclusive evaluation date")
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--out", type=Path, default=Path("/tmp/juslag_information_time_audit.csv"))
    args = parser.parse_args()
    us_dates, jp_dates, training_dates = load_input_dates(args.db, args.sample_start, args.end, args.mode)
    us_close_times = market_close_times("NYSE", args.sample_start, args.end)
    jp_close_times = market_close_times("JPX", args.sample_start, args.end)
    last_observed_at = load_last_observations(args.db, args.mode)
    rows = audit_dates(us_dates, jp_dates, pretrain_end=args.pretrain_end, window=args.window,
                       start=args.start, training_dates=training_dates,
                       us_close_times=us_close_times, jp_close_times=jp_close_times,
                       last_observed_at=last_observed_at)
    if not rows:
        raise SystemExit("No auditable dates in raw price cache")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    failures = sum(row["date_order"] == "fail" for row in rows)
    not_historical = sum(row["audit_result"] == "not_historical_signal" for row in rows)
    blocked = sum(row["audit_result"] == "blocked_gap_same_open_fill" for row in rows)
    unverified_close = sum(row["market_close_before_deadline"] != "yes" for row in rows)
    observed_before = sum(row["latest_input_observation_status"] == "recorded_before_deadline" for row in rows)
    print(f"rows={len(rows)} non_historical_sessions={not_historical} date_order_failures={failures} "
          f"same_open_blocked={blocked} close_time_unverified={unverified_close} "
          f"latest_inputs_observed_before_deadline={observed_before} out={args.out}")


if __name__ == "__main__":
    main()
