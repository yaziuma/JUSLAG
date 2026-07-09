from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from juslag.cache import PriceCache


def test_raw_and_adjusted_are_isolated(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "prices.db")
    idx = pd.to_datetime(["2026-04-07"])

    cache.upsert("SPY", pd.Series([100.0], index=idx), pd.Series([101.0], index=idx), price_mode="raw")
    cache.upsert("SPY", pd.Series([80.0], index=idx), pd.Series([81.0], index=idx), price_mode="adjusted")

    raw_loaded = cache.load(["SPY"], "2026-04-01", "2026-04-10", price_mode="raw")
    adjusted_loaded = cache.load(["SPY"], "2026-04-01", "2026-04-10", price_mode="adjusted")

    assert float(raw_loaded["SPY"]["close"].iloc[0]) == 101.0
    assert float(adjusted_loaded["SPY"]["close"].iloc[0]) == 81.0


def test_summary_and_freshness_are_mode_specific(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "prices.db")
    idx = pd.to_datetime(["2026-04-06", "2026-04-07"])

    cache.upsert("SPY", pd.Series([100.0, 101.0], index=idx), pd.Series([101.0, 102.0], index=idx), price_mode="raw")
    cache.upsert("1306.T", pd.Series([200.0, 201.0], index=idx), pd.Series([201.0, 202.0], index=idx), price_mode="raw")
    cache.upsert("SPY", pd.Series([90.0], index=pd.to_datetime(["2026-04-01"])), pd.Series([91.0], index=pd.to_datetime(["2026-04-01"])), price_mode="adjusted")

    raw_summary = cache.summary(["SPY"], ["1306.T"], required_latest_date="2026-04-07", price_mode="raw")
    adjusted_summary = cache.summary(["SPY"], ["1306.T"], required_latest_date="2026-04-07", price_mode="adjusted")

    assert raw_summary["daily_signal_ready"] is True
    assert adjusted_summary["daily_signal_ready"] is False
    assert raw_summary["price_mode"] == "raw"
    assert adjusted_summary["missing_tickers"] == ["1306.T"]

    adjusted_freshness = cache.freshness_report(["SPY", "1306.T"], required_latest_date="2026-04-07", price_mode="adjusted")
    assert adjusted_freshness["freshness_ok"] is False
    assert "1306.T" in adjusted_freshness["missing_tickers"]


def test_legacy_schema_is_rebuilt_safely(tmp_path: Path) -> None:
    db_path = tmp_path / "prices.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE prices (
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL,
                close REAL,
                PRIMARY KEY (ticker, date)
            )
            """
        )
        conn.execute(
            "INSERT INTO prices(ticker, date, open, close) VALUES ('SPY', '2026-04-07', 100.0, 101.0)"
        )

    cache = PriceCache(db_path)
    with sqlite3.connect(db_path) as conn:
        cols = cache._existing_price_columns(conn)
        indexes = conn.execute("PRAGMA index_list(prices)").fetchall()
    assert "price_mode" in cols
    assert any("idx_ticker_price_mode_date" == idx[1] for idx in indexes)

    stats_raw = cache.stats("raw")
    assert stats_raw.empty
