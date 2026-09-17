"""Measure the effect of computing returns before versus after common-day alignment."""
from __future__ import annotations

import argparse
import json

import pandas as pd

from juslag.cache import DEFAULT_DB_PATH, PriceCache
from juslag.config import JP_TICKERS, US_TICKERS
from juslag.data_loader import repair_known_bad_prices


def compare_return_order(close: pd.DataFrame, us: list[str], jp: list[str]) -> dict[str, object]:
    us_days = close[us].dropna(how="all").index
    jp_days = close[jp].dropna(how="all").index
    common = us_days.intersection(jp_days)
    market_first = pd.concat([
        close.loc[us_days, us].pct_change(fill_method=None).reindex(common),
        close.loc[jp_days, jp].pct_change(fill_method=None).reindex(common),
    ], axis=1)
    common_first = close.loc[common, us + jp].pct_change(fill_method=None)
    delta = (market_first - common_first).abs()
    different = delta.gt(1e-12)
    valid = delta.notna()
    by_market = {}
    for name, tickers in (("us", us), ("jp", jp)):
        block = delta[tickers]
        mask = different[tickers]
        by_market[name] = {
            "different_days": int(mask.any(axis=1).sum()),
            "different_cells": int(mask.sum().sum()),
            "mean_abs_bps_on_different_cells": round(float(block.where(mask).stack().mean() * 10_000), 3)
            if mask.any().any() else 0.0,
            "max_abs_bps": round(float(block.max().max() * 10_000), 3),
        }
    return {
        "common_days": len(common),
        "us_only_days": len(us_days.difference(jp_days)),
        "jp_only_days": len(jp_days.difference(us_days)),
        "comparable_cells": int(valid.sum().sum()),
        "different_days": int(different.any(axis=1).sum()),
        "different_cells": int(different.sum().sum()),
        "by_market": by_market,
        "first_different_dates": [str(day.date()) for day in different.any(axis=1).loc[lambda x: x].index[:10]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--start", default="2018-07-01")
    parser.add_argument("--end", default="2026-09-17")
    args = parser.parse_args()
    us, jp = list(US_TICKERS), list(JP_TICKERS)
    tickers = us + jp
    frames = PriceCache(args.db).load(tickers, args.start, args.end, price_mode="adjusted")
    if set(frames) != set(tickers):
        raise SystemExit(f"Missing tickers: {sorted(set(tickers) - set(frames))}")
    close = pd.DataFrame({ticker: frames[ticker]["close"] for ticker in tickers}).sort_index()
    open_ = pd.DataFrame({ticker: frames[ticker]["open"] for ticker in tickers}).sort_index()
    _, close = repair_known_bad_prices(open_, close)
    print(json.dumps(compare_return_order(close, us, jp), indent=2))


if __name__ == "__main__":
    main()
