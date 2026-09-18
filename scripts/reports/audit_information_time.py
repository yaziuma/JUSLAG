"""Audit historical signal/input/execution dates from the local raw price cache."""
from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

import pandas as pd

from juslag.cache import DEFAULT_DB_PATH
from juslag.config import JP_TICKERS, US_TICKERS


def audit_dates(
    us_dates: pd.DatetimeIndex,
    jp_dates: pd.DatetimeIndex,
    *,
    pretrain_end: str,
    window: int,
    start: str = "2022-01-01",
) -> list[dict[str, str]]:
    """Use market-session dates; a row does not prove its publication timestamp."""
    us_dates = us_dates.sort_values().unique()
    jp_dates = jp_dates.sort_values().unique()
    common = us_dates.intersection(jp_dates)
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
        rows.append({
            "signal_date": signal_date.date().isoformat(),
            "signal_path": "historical_common_day" if signal_date in common else "us_only_not_historical_signal",
            "last_training_common_date": last_training.date().isoformat(),
            "last_us_input_date": signal_date.date().isoformat(),
            "last_jp_input_date": jp_input.date().isoformat() if pd.notna(jp_input) else "",
            "execution_jp_date": execution.date().isoformat() if pd.notna(execution) else "",
            "date_order": "ok" if date_order_ok else "fail",
            "price_publication_time": "unverified",
            "gap_after_open_fill": "unverified_same_open_assumption",
        })
    return rows


def load_market_dates(db_path: Path, tickers: list[str], end: str) -> pd.DatetimeIndex:
    placeholders = ",".join("?" for _ in tickers)
    uri = f"file:{db_path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        rows = conn.execute(
            f"SELECT DISTINCT date FROM prices WHERE price_mode = ? AND close IS NOT NULL "
            f"AND date < ? AND ticker IN ({placeholders}) ORDER BY date",
            ("raw", end, *tickers),
        ).fetchall()
    return pd.DatetimeIndex([row[0] for row in rows])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--end", default="2026-09-19", help="Exclusive YYYY-MM-DD")
    parser.add_argument("--pretrain-end", default="2021-12-31")
    parser.add_argument("--start", default="2022-01-01", help="Inclusive evaluation date")
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--out", type=Path, default=Path("/tmp/juslag_information_time_audit.csv"))
    args = parser.parse_args()
    us_dates = load_market_dates(args.db, list(US_TICKERS), args.end)
    jp_dates = load_market_dates(args.db, list(JP_TICKERS), args.end)
    rows = audit_dates(us_dates, jp_dates, pretrain_end=args.pretrain_end, window=args.window, start=args.start)
    if not rows:
        raise SystemExit("No auditable dates in raw price cache")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    failures = sum(row["date_order"] == "fail" for row in rows)
    us_only = sum(row["signal_path"] == "us_only_not_historical_signal" for row in rows)
    print(f"rows={len(rows)} us_only_sessions={us_only} date_order_failures={failures} out={args.out}")


if __name__ == "__main__":
    main()
