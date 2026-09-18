from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from juslag.cache import PriceCache
from juslag.services.daily_signal import build_freshness


def test_raw_and_adjusted_are_isolated(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "prices.db")
    idx = pd.to_datetime(["2026-04-07"])

    cache.upsert("SPY", pd.Series([100.0], index=idx), pd.Series([101.0], index=idx), price_mode="raw")
    cache.upsert("SPY", pd.Series([80.0], index=idx), pd.Series([81.0], index=idx), price_mode="adjusted")

    raw_loaded = cache.load(["SPY"], "2026-04-01", "2026-04-10", price_mode="raw")
    adjusted_loaded = cache.load(["SPY"], "2026-04-01", "2026-04-10", price_mode="adjusted")

    assert float(raw_loaded["SPY"]["close"].iloc[0]) == 101.0
    assert float(adjusted_loaded["SPY"]["close"].iloc[0]) == 81.0


def test_price_observations_record_first_seen_and_revisions_only(tmp_path: Path) -> None:
    db_path = tmp_path / "prices.db"
    cache = PriceCache(db_path)
    idx = pd.to_datetime(["2026-09-18"])
    opens = pd.Series([100.0], index=idx)
    first_close = pd.Series([101.0], index=idx)
    revised_close = pd.Series([102.0], index=idx)

    cache.upsert("SPY", opens, first_close, price_mode="raw")
    cache.upsert("SPY", opens, first_close, price_mode="raw")
    cache.upsert("SPY", opens, revised_close, price_mode="raw")

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT open, close, observed_at_utc FROM price_observations "
            "WHERE ticker = 'SPY' AND date = '2026-09-18' ORDER BY observed_at_utc"
        ).fetchall()
    assert len(rows) == 2
    assert [row[1] for row in rows] == [101.0, 102.0]
    assert all(row[2].endswith("+00:00") for row in rows)


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


def test_summary_allows_jp_holiday_but_not_missing_prior_session(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "prices.db")
    us_date = pd.to_datetime(["2026-05-04"])
    jp_date = pd.to_datetime(["2026-05-01"])
    cache.upsert("SPY", pd.Series([100.0], index=us_date), pd.Series([101.0], index=us_date), price_mode="raw")
    cache.upsert("1306.T", pd.Series([200.0], index=jp_date), pd.Series([201.0], index=jp_date), price_mode="raw")

    summary = cache.summary(["SPY"], ["1306.T"], required_latest_date="2026-05-04", required_latest_jp_date="2026-05-01", price_mode="raw")
    assert summary["daily_signal_ready"] is True
    assert summary["stale_tickers"] == []

    stale = cache.summary(["SPY"], ["1306.T"], required_latest_date="2026-05-04", required_latest_jp_date="2026-05-02", price_mode="raw")
    assert stale["daily_signal_ready"] is False
    assert stale["stale_tickers"] == ["1306.T"]


def test_daily_freshness_uses_last_jpx_session(tmp_path: Path) -> None:
    cache = PriceCache(tmp_path / "prices.db")
    us_date = pd.to_datetime(["2026-05-04"])
    jp_date = pd.to_datetime(["2026-05-01"])
    cache.upsert("SPY", pd.Series([100.0], index=us_date), pd.Series([101.0], index=us_date), price_mode="raw")
    cache.upsert("1306.T", pd.Series([200.0], index=jp_date), pd.Series([201.0], index=jp_date), price_mode="raw")

    freshness = build_freshness(cache, ["SPY"], ["1306.T"], "2026-05-04", "raw")
    assert freshness["required_jp_date"] == "2026-05-01"
    assert freshness["jp_calendar_verified"] is True
    assert freshness["freshness_ok"] is True

    cache.upsert("SPY", pd.Series([100.0], index=us_date), pd.Series([101.0], index=us_date), price_mode="adjusted")
    cache.upsert("1306.T", pd.Series([200.0], index=pd.to_datetime(["2026-04-30"])), pd.Series([201.0], index=pd.to_datetime(["2026-04-30"])), price_mode="adjusted")
    stale = build_freshness(cache, ["SPY"], ["1306.T"], "2026-05-04", "adjusted")
    assert stale["freshness_ok"] is False
    assert "1306.T" in stale["stale_tickers"]


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
