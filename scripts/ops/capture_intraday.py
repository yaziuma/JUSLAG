"""Capture recent JP ETF intraday bars with observation timestamps for A2 research."""
from __future__ import annotations

import argparse
import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from juslag.config import JP_TICKERS

_SNAPSHOT_FIELDS = ("ticker", "bar_start_utc", "observed_at_utc", "open", "high", "low", "close", "volume")


def store_capture(db_path: Path, bars: pd.DataFrame, observed_at_utc: datetime,
                  interval: str = "5m") -> dict[str, int]:
    if observed_at_utc.tzinfo is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = observed_at_utc.astimezone(timezone.utc).isoformat()
    counts: dict[str, int] = {}
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS intraday_bars (
                ticker TEXT NOT NULL,
                interval TEXT NOT NULL,
                bar_start_utc TEXT NOT NULL,
                observed_at_utc TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER,
                PRIMARY KEY (ticker, interval, bar_start_utc, observed_at_utc)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS intraday_bars_time ON intraday_bars(bar_start_utc, ticker)")
        for ticker in JP_TICKERS:
            if ticker not in bars.columns.get_level_values(0):
                continue
            frame = bars[ticker].dropna(subset=["Open", "High", "Low", "Close"])
            rows = []
            for bar_start, bar in frame.iterrows():
                bar_utc = pd.Timestamp(bar_start).tz_convert("UTC").isoformat()
                if bar_utc > stamp:
                    continue
                volume = bar.get("Volume")
                rows.append((ticker, interval, bar_utc, stamp, float(bar["Open"]),
                             float(bar["High"]), float(bar["Low"]), float(bar["Close"]),
                             None if pd.isna(volume) else int(volume)))
            conn.executemany("INSERT OR IGNORE INTO intraday_bars VALUES (?,?,?,?,?,?,?,?,?)", rows)
            counts[ticker] = len(rows)
    return counts


def opening_snapshot_rows(bars: pd.DataFrame, observed_at_utc: datetime) -> list[dict]:
    """Keep only bars from today's JP opening window, with actual observation time."""
    if observed_at_utc.tzinfo is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    observed = pd.Timestamp(observed_at_utc).tz_convert("UTC")
    jst_day = observed.tz_convert("Asia/Tokyo").date()
    rows = []
    for ticker in JP_TICKERS:
        if ticker not in bars.columns.get_level_values(0):
            continue
        for bar_start, bar in bars[ticker].dropna(subset=["Open", "High", "Low", "Close"]).iterrows():
            timestamp = pd.Timestamp(bar_start).tz_convert("UTC")
            local = timestamp.tz_convert("Asia/Tokyo")
            if local.date() != jst_day or not "09:00" <= local.strftime("%H:%M") <= "09:30":
                continue
            if timestamp > observed:
                continue
            volume = bar.get("Volume")
            rows.append({
                "ticker": ticker, "bar_start_utc": timestamp.isoformat(),
                "observed_at_utc": observed.isoformat(),
                "open": float(bar["Open"]), "high": float(bar["High"]),
                "low": float(bar["Low"]), "close": float(bar["Close"]),
                "volume": "" if pd.isna(volume) else int(volume),
            })
    return rows


def append_opening_snapshot(snapshot_dir: Path, rows: list[dict], observed_at_utc: datetime) -> Path | None:
    if not rows:
        return None
    day = observed_at_utc.astimezone(ZoneInfo("Asia/Tokyo")).date().isoformat()
    path = snapshot_dir / f"{day}.csv"
    existing = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as file:
            existing = list(csv.DictReader(file))
    versions = {(row["ticker"], row["bar_start_utc"], row["observed_at_utc"]): row for row in existing}
    for row in rows:
        versions[(row["ticker"], row["bar_start_utc"], row["observed_at_utc"])] = row
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=_SNAPSHOT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(versions[key] for key in sorted(versions))
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/intraday/prices.sqlite"))
    parser.add_argument("--period", default="5d")
    parser.add_argument("--snapshot-dir", type=Path, default=None)
    args = parser.parse_args()
    bars = yf.download(list(JP_TICKERS), period=args.period, interval="5m",
                       auto_adjust=False, group_by="ticker", progress=False, threads=True)
    observed_at = datetime.now(timezone.utc)
    if bars.empty:
        raise SystemExit("No intraday bars returned; no data saved")
    counts = store_capture(args.db, bars, observed_at)
    if args.snapshot_dir is not None:
        snapshot_rows = opening_snapshot_rows(bars, observed_at)
        snapshot = append_opening_snapshot(args.snapshot_dir, snapshot_rows, observed_at)
        print(f"opening_snapshot={snapshot} rows={len(snapshot_rows)}")
    if not counts or sum(counts.values()) == 0:
        raise SystemExit("No valid intraday bars returned; no data saved")
    print(f"observed_at_utc={observed_at.isoformat()} tickers={len(counts)} "
          f"bars={sum(counts.values())} db={args.db}")
    if len(counts) != len(JP_TICKERS):
        raise SystemExit(f"Incomplete ticker coverage: {sorted(set(JP_TICKERS) - set(counts))}")


if __name__ == "__main__":
    main()
