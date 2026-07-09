from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import pandas as pd
import yfinance as yf

from juslag.cache import PriceCache

logger = logging.getLogger(__name__)

_cache = PriceCache()
FillPolicy = Literal["strict", "rolling_mean"]
PriceMode = Literal["adjusted", "raw"]


@dataclass
class DataQuality:
    sample_start: str
    sample_end: str
    fill_policy: FillPolicy
    price_mode: PriceMode
    filled_cells: int
    dropped_us_tickers: list[str]
    dropped_jp_tickers: list[str]
    effective_start: str | None
    effective_end: str | None
    joint_rows: int
    effective_window_days: int
    usable_us_tickers: int
    usable_jp_tickers: int
    cache_first_date: str | None
    cache_last_date: str | None
    cache_price_mode: PriceMode
    cache_isolated_by_price_mode: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "sample_start": self.sample_start,
            "sample_end": self.sample_end,
            "fill_policy": self.fill_policy,
            "price_mode": self.price_mode,
            "filled_cells": self.filled_cells,
            "dropped_us_tickers": self.dropped_us_tickers,
            "dropped_jp_tickers": self.dropped_jp_tickers,
            "effective_start": self.effective_start,
            "effective_end": self.effective_end,
            "joint_rows": self.joint_rows,
            "effective_window_days": self.effective_window_days,
            "usable_us_tickers": self.usable_us_tickers,
            "usable_jp_tickers": self.usable_jp_tickers,
            "cache_first_date": self.cache_first_date,
            "cache_last_date": self.cache_last_date,
            "cache_price_mode": self.cache_price_mode,
            "cache_isolated_by_price_mode": self.cache_isolated_by_price_mode,
        }


def _fill_small_gaps(df: pd.DataFrame, rolling_window: int = 5) -> pd.DataFrame:
    """Fill small download gaps with short rolling mean.

    Intended for sparse missing values from provider glitches, not for holiday mismatches.
    """
    return df.apply(lambda col: col.fillna(col.rolling(rolling_window, min_periods=1).mean()))


def _fetch_group_with_cache(
    tickers: list[str], start: str, end: str, cache: PriceCache, price_mode: PriceMode = "adjusted"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch open/close prices for a ticker group using SQLite cache + incremental download.

    1. Find min latest_date across all tickers (conservative: re-download if any is stale).
    2. Download only the delta from (min_latest - 7d) to end and upsert to cache.
    3. Load full [start, end) from cache and return (close_df, open_df).
    """
    ranges = [cache.date_range(t, price_mode=price_mode) for t in tickers]
    earliest_list = [r[0] for r in ranges if r[0] is not None]
    latest_list = [r[1] for r in ranges if r[1] is not None]

    if len(latest_list) == len(tickers) and earliest_list and min(earliest_list) <= start:
        # Cache fully covers the requested start — download only the fresh tail
        overlap_start = (pd.Timestamp(min(latest_list)) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        dl_start = max(overlap_start, start)
    else:
        # Cache doesn't cover requested start (or missing) — download from start
        dl_start = start

    logger.info("Incremental download: %d tickers [%s, %s) (cache start=%s)", len(tickers), dl_start, end, start)
    raw = yf.download(
        tickers,
        start=dl_start,
        end=end,
        auto_adjust=(price_mode == "adjusted"),
        progress=False,
    )

    if not raw.empty:
        close_raw = raw["Close"]
        open_raw = raw["Open"]
        # yfinance returns Series for single ticker, DataFrame for multiple
        if isinstance(close_raw, pd.Series):
            close_raw = close_raw.to_frame(tickers[0])
            open_raw = open_raw.to_frame(tickers[0])
        for ticker in tickers:
            if ticker in close_raw.columns:
                n = cache.upsert(ticker, open_raw[ticker], close_raw[ticker], price_mode=price_mode)
                logger.debug("Upserted %d rows for %s", n, ticker)

    cached = cache.load(tickers, start, end, price_mode=price_mode)
    close_frames = [cached[t]["close"].rename(t) for t in tickers if t in cached]
    open_frames = [cached[t]["open"].rename(t) for t in tickers if t in cached]

    close_df = pd.concat(close_frames, axis=1) if close_frames else pd.DataFrame()
    open_df = pd.concat(open_frames, axis=1) if open_frames else pd.DataFrame()
    return close_df, open_df


def fetch_data(
    us_tickers: list[str],
    jp_tickers: list[str],
    start: str,
    end: str,
    price_mode: PriceMode = "adjusted",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fetch Open/Close prices using SQLite cache — only downloads missing date ranges."""
    us_close, _ = _fetch_group_with_cache(us_tickers, start, end, _cache, price_mode=price_mode)
    jp_close, jp_open = _fetch_group_with_cache(jp_tickers, start, end, _cache, price_mode=price_mode)

    us_close = us_close.reindex(columns=us_tickers).dropna(how="all").dropna(axis=1, how="all")
    jp_close = jp_close.reindex(columns=jp_tickers).dropna(how="all").dropna(axis=1, how="all")
    jp_open = jp_open.reindex(columns=jp_tickers).dropna(how="all").dropna(axis=1, how="all")

    logger.info(
        "fetch_data via cache: us_close=%s jp_close=%s jp_open=%s",
        us_close.shape, jp_close.shape, jp_open.shape,
    )
    return us_close, jp_close, jp_open


def compute_returns(us_close: pd.DataFrame, jp_close: pd.DataFrame, jp_open: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute US CTC, JP OTC, and JP CTC returns."""
    us_cc = us_close.pct_change()
    jp_oc = jp_close / jp_open - 1.0
    jp_cc = jp_close.pct_change()
    logger.info("Computed returns: us_cc=%s jp_oc=%s jp_cc=%s", us_cc.shape, jp_oc.shape, jp_cc.shape)
    return us_cc, jp_oc, jp_cc


def build_joint_cc(
    us_cc: pd.DataFrame,
    jp_cc: pd.DataFrame,
    us_ratio: float = 0.8,
    jp_ratio: float = 0.8,
    fill_policy: FillPolicy = "strict",
    sample_start: str | None = None,
    sample_end: str | None = None,
    price_mode: PriceMode = "adjusted",
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build aligned US+JP close-to-close return matrix.

    Holiday differences are handled by intersection of available dates.
    Data-acquisition missings are then filtered/fillled in a second step.
    """
    us_tickers = us_cc.columns.tolist()
    jp_tickers = jp_cc.columns.tolist()

    common_idx = us_cc.index.intersection(jp_cc.index)
    joint_cc = pd.concat([us_cc.loc[common_idx], jp_cc.loc[common_idx]], axis=1)

    us_valid = joint_cc[us_tickers].notna().sum(axis=1) >= len(us_tickers) * us_ratio
    jp_valid = joint_cc[jp_tickers].notna().sum(axis=1) >= len(jp_tickers) * jp_ratio
    joint_cc = joint_cc[us_valid & jp_valid]

    raw_joint = joint_cc.copy()
    if fill_policy == "rolling_mean":
        joint_cc = _fill_small_gaps(joint_cc)
    elif fill_policy != "strict":
        raise ValueError(f"Unsupported fill_policy: {fill_policy}")
    filled_cells = int((raw_joint.isna() & joint_cc.notna()).sum().sum())
    joint_cc = joint_cc.dropna()
    dropped = (raw_joint.notna().sum(axis=0) == 0)
    dropped_us_tickers = [t for t in us_tickers if dropped.get(t, False)]
    dropped_jp_tickers = [t for t in jp_tickers if dropped.get(t, False)]
    cache_min, cache_max = _cache.global_date_range(price_mode=price_mode)
    quality = DataQuality(
        sample_start=sample_start or (str(joint_cc.index.min().date()) if not joint_cc.empty else ""),
        sample_end=sample_end or (str(joint_cc.index.max().date()) if not joint_cc.empty else ""),
        fill_policy=fill_policy,
        price_mode=price_mode,
        filled_cells=filled_cells,
        dropped_us_tickers=dropped_us_tickers,
        dropped_jp_tickers=dropped_jp_tickers,
        effective_start=str(joint_cc.index.min().date()) if not joint_cc.empty else None,
        effective_end=str(joint_cc.index.max().date()) if not joint_cc.empty else None,
        joint_rows=int(len(joint_cc)),
        effective_window_days=int(len(joint_cc)),
        usable_us_tickers=int(joint_cc[us_tickers].shape[1]),
        usable_jp_tickers=int(joint_cc[jp_tickers].shape[1]),
        cache_first_date=cache_min,
        cache_last_date=cache_max,
        cache_price_mode=price_mode,
        cache_isolated_by_price_mode=True,
    ).to_dict()
    logger.info("Built joint return matrix: %s", joint_cc.shape)
    return joint_cc, quality
