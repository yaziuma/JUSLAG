from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Literal

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".juslag" / "prices.db"
PriceMode = Literal["raw", "adjusted"]
PRICE_MODES: tuple[PriceMode, PriceMode] = ("raw", "adjusted")


class PriceCache:
    """SQLite-backed local price cache for incremental yfinance downloads.

    Schema: prices(ticker TEXT, date TEXT, price_mode TEXT, open REAL, close REAL,
    PK(ticker, date, price_mode))
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info("PriceCache at %s", self.db_path)

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            existing_cols = self._existing_price_columns(conn)
            if existing_cols and "price_mode" not in existing_cols:
                logger.warning(
                    "legacy price cache schema detected; rebuilding cache for price_mode isolation: %s",
                    self.db_path,
                )
                conn.execute("DROP TABLE prices")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prices (
                    ticker TEXT NOT NULL,
                    date   TEXT NOT NULL,
                    price_mode TEXT NOT NULL,
                    open   REAL,
                    close  REAL,
                    PRIMARY KEY (ticker, date, price_mode)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ticker_price_mode_date ON prices (ticker, price_mode, date)"
            )

    @staticmethod
    def _existing_price_columns(conn: sqlite3.Connection) -> set[str]:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prices'"
        ).fetchone()
        if not table_exists:
            return set()
        columns = conn.execute("PRAGMA table_info(prices)").fetchall()
        return {str(col[1]) for col in columns}

    def date_range(self, ticker: str, price_mode: PriceMode) -> tuple[str | None, str | None]:
        """Return (earliest, latest) ISO dates for ticker+mode, or (None, None)."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT MIN(date), MAX(date) FROM prices WHERE ticker = ? AND price_mode = ?",
                (ticker, price_mode),
            ).fetchone()
        if row and row[0]:
            return row[0], row[1]
        return None, None

    def latest_date(self, ticker: str, price_mode: PriceMode) -> str | None:
        """Return ISO date of the most recent cached row for mode, or None."""
        _, latest = self.date_range(ticker, price_mode)
        return latest

    def load(
        self, tickers: list[str], start: str, end: str, price_mode: PriceMode
    ) -> dict[str, pd.DataFrame]:
        """Load {ticker: DataFrame(open, close)} for date in [start, end) by mode."""
        result: dict[str, pd.DataFrame] = {}
        with sqlite3.connect(self.db_path) as conn:
            for ticker in tickers:
                rows = conn.execute(
                    "SELECT date, open, close FROM prices "
                    "WHERE ticker = ? AND price_mode = ? AND date >= ? AND date < ? ORDER BY date",
                    (ticker, price_mode, start, end),
                ).fetchall()
                if rows:
                    df = pd.DataFrame(rows, columns=["date", "open", "close"])
                    df["date"] = pd.to_datetime(df["date"])
                    result[ticker] = df.set_index("date")
        return result

    def upsert(
        self, ticker: str, open_s: pd.Series, close_s: pd.Series, price_mode: PriceMode
    ) -> int:
        """Insert or replace rows for ticker+mode. Returns row count written."""
        idx = open_s.index.union(close_s.index)
        rows = []
        for d in idx:
            o = open_s.get(d)
            c = close_s.get(d)
            if pd.isna(o) and pd.isna(c):
                continue
            rows.append(
                (
                    ticker,
                    str(d.date()),
                    price_mode,
                    None if pd.isna(o) else float(o),
                    None if pd.isna(c) else float(c),
                )
            )
        if not rows:
            return 0
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO prices(ticker, date, price_mode, open, close) VALUES(?,?,?,?,?)",
                rows,
            )
        return len(rows)

    def stats(self, price_mode: PriceMode) -> pd.DataFrame:
        """Return per-ticker row counts and date range for inspection by mode."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT ticker, COUNT(*) as rows, MIN(date) as first, MAX(date) as last "
                "FROM prices WHERE price_mode = ? GROUP BY ticker ORDER BY ticker",
                (price_mode,),
            ).fetchall()
        return pd.DataFrame(rows, columns=["ticker", "rows", "first", "last"])

    def global_date_range(self, price_mode: PriceMode) -> tuple[str | None, str | None]:
        """Return global (earliest, latest) ISO dates over all tickers for mode."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT MIN(date), MAX(date) FROM prices WHERE price_mode = ?", (price_mode,)
            ).fetchone()
        if row and row[0]:
            return row[0], row[1]
        return None, None

    def summary(
        self,
        us_tickers: list[str] | None = None,
        jp_tickers: list[str] | None = None,
        required_latest_date: str | None = None,
        price_mode: PriceMode = "adjusted",
    ) -> dict[str, object]:
        """Return aggregate freshness summary for a single price mode."""
        us_tickers = us_tickers or []
        jp_tickers = jp_tickers or []
        stats = self.stats(price_mode)
        if stats.empty:
            return {
                "price_mode": price_mode,
                "cache_rows_for_mode": 0,
                "us_latest_min": None,
                "us_latest_max": None,
                "jp_latest_min": None,
                "jp_latest_max": None,
                "latest_dates_aligned": False,
                "missing_tickers": us_tickers + jp_tickers,
                "stale_tickers": us_tickers + jp_tickers if required_latest_date else [],
                "daily_signal_ready": False,
            }

        by_ticker = stats.set_index("ticker")
        us_rows = by_ticker.reindex(us_tickers).dropna(how="all")
        jp_rows = by_ticker.reindex(jp_tickers).dropna(how="all")
        us_latest = (
            pd.to_datetime(us_rows["last"], errors="coerce")
            if not us_rows.empty
            else pd.Series(dtype="datetime64[ns]")
        )
        jp_latest = (
            pd.to_datetime(jp_rows["last"], errors="coerce")
            if not jp_rows.empty
            else pd.Series(dtype="datetime64[ns]")
        )
        all_latest = pd.concat([us_latest, jp_latest], axis=0)
        tracked_tickers = us_tickers + jp_tickers
        missing = [t for t in tracked_tickers if t not in by_ticker.index]
        stale_tickers: list[str] = []
        if required_latest_date:
            req = pd.Timestamp(required_latest_date)
            stale_tickers = [
                t
                for t in tracked_tickers
                if t in by_ticker.index and pd.Timestamp(by_ticker.loc[t, "last"]) < req
            ]
        # US と JP の最新日が異なるのは戦略上の正常状態（US クローズ翌朝に JP 市場が開く）
        # 「整合」の定義: US 銘柄同士が揃っている、かつ JP 銘柄同士が揃っていること
        # US と JP の日付が異なること自体はエラーではない
        us_aligned = bool(not us_latest.empty and us_latest.min() == us_latest.max())
        jp_aligned = bool(not jp_latest.empty and jp_latest.min() == jp_latest.max())
        latest_aligned = us_aligned and jp_aligned
        return {
            "price_mode": price_mode,
            "cache_rows_for_mode": int(stats["rows"].sum()),
            "us_latest_min": us_latest.min().date().isoformat() if not us_latest.empty else None,
            "us_latest_max": us_latest.max().date().isoformat() if not us_latest.empty else None,
            "jp_latest_min": jp_latest.min().date().isoformat() if not jp_latest.empty else None,
            "jp_latest_max": jp_latest.max().date().isoformat() if not jp_latest.empty else None,
            "latest_dates_aligned": latest_aligned,
            "missing_tickers": missing,
            "stale_tickers": stale_tickers,
            "daily_signal_ready": bool(not missing and not stale_tickers and latest_aligned),
        }

    def export_tail(
        self, tickers: list[str], since_date: str, price_mode: PriceMode
    ) -> pd.DataFrame:
        """Return rows (ticker, date, open, close) with date >= since_date, ordered by ticker, date."""
        if not tickers:
            return pd.DataFrame(columns=["ticker", "date", "open", "close"])
        placeholders = ",".join("?" for _ in tickers)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT ticker, date, open, close FROM prices "
                f"WHERE ticker IN ({placeholders}) AND price_mode = ? AND date >= ? "
                f"ORDER BY ticker, date",
                (*tickers, price_mode, since_date),
            ).fetchall()
        return pd.DataFrame(rows, columns=["ticker", "date", "open", "close"])

    def freshness_report(
        self,
        tickers: list[str],
        required_latest_date: str | None = None,
        price_mode: PriceMode = "adjusted",
    ) -> dict[str, object]:
        """Return freshness and missing report for tickers in one price mode."""
        stats = self.stats(price_mode)
        if stats.empty:
            return {
                "price_mode": price_mode,
                "freshness_ok": False,
                "latest_date": None,
                "stale_tickers": tickers,
                "missing_tickers": tickers,
            }
        by_ticker = stats.set_index("ticker")
        existing = [t for t in tickers if t in by_ticker.index]
        missing = [t for t in tickers if t not in by_ticker.index]
        latest_series = (
            pd.to_datetime(by_ticker.loc[existing, "last"], errors="coerce")
            if existing
            else pd.Series(dtype="datetime64[ns]")
        )
        stale: list[str] = []
        if required_latest_date:
            req = pd.Timestamp(required_latest_date)
            stale = [t for t in existing if pd.Timestamp(by_ticker.loc[t, "last"]) < req]
        return {
            "price_mode": price_mode,
            "freshness_ok": bool(existing and not missing and not stale),
            "latest_date": latest_series.max().date().isoformat() if not latest_series.empty else None,
            "stale_tickers": stale,
            "missing_tickers": missing,
        }
