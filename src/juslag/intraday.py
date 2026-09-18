"""Read observed 5-minute opening bars from local SQLite or committed snapshots."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


def load_intraday_bars(*, db: Path | None = None, snapshot_dir: Path | None = None) -> pd.DataFrame:
    if (db is None) == (snapshot_dir is None):
        raise ValueError("Specify exactly one intraday source")
    if db is not None:
        with sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True) as conn:
            bars = pd.read_sql_query("""
                SELECT ticker, bar_start_utc, observed_at_utc, open
                FROM intraday_bars WHERE interval = '5m'
            """, conn)
    else:
        paths = sorted(snapshot_dir.glob("????-??-??.csv"))
        bars = pd.concat((pd.read_csv(path) for path in paths), ignore_index=True) if paths else pd.DataFrame()
    if bars.empty:
        return pd.DataFrame(columns=["ticker", "bar_start_utc", "observed_at_utc", "open"])
    needed = {"ticker", "bar_start_utc", "observed_at_utc", "open"}
    if not needed.issubset(bars):
        raise ValueError(f"Missing intraday columns: {sorted(needed - set(bars))}")
    return (bars.sort_values("observed_at_utc")
            .drop_duplicates(["ticker", "bar_start_utc"], keep="first")
            .loc[:, ["ticker", "bar_start_utc", "observed_at_utc", "open"]]
            .reset_index(drop=True))
