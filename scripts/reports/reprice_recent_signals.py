"""Reprice recent paper-aligned signals with observed post-open bar proxies."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import pandas as pd

from juslag.cache import DEFAULT_DB_PATH, PriceCache
from juslag.config import JP_CYCLICAL, JP_TICKERS, US_CYCLICAL, US_TICKERS
from juslag.data_loader import build_joint_cc, compute_returns, repair_known_bad_prices
from juslag.intraday import load_intraday_bars
from juslag.prior import build_prior_eigenvectors, build_prior_exposure
from juslag.signal import generate_signals


def reprice_signals(
    signals: pd.DataFrame,
    jp_open: pd.DataFrame,
    jp_close: pd.DataFrame,
    intraday: pd.DataFrame,
    q: float = 0.3,
) -> tuple[list[dict], list[dict]]:
    """Use first observed 09:10-09:30 bar; never claim it is an actual fill."""
    if not 0 < q < 0.5:
        raise ValueError("q must be between 0 and 0.5")
    bars = intraday.copy()
    bars["jst"] = pd.to_datetime(bars["bar_start_utc"], utc=True).dt.tz_convert("Asia/Tokyo")
    bars["day"] = bars["jst"].dt.strftime("%Y-%m-%d")
    bars["clock"] = bars["jst"].dt.strftime("%H:%M")
    bars = bars[(bars["clock"] >= "09:10") & (bars["clock"] <= "09:30")]
    bars = bars.sort_values("jst").drop_duplicates(["ticker", "day"])
    bar_lookup = {(row.ticker, row.day): row for row in bars.itertuples()}
    jp_dates = jp_open.index.intersection(jp_close.index).sort_values()
    covered_days = set(pd.to_datetime(intraday["bar_start_utc"], utc=True).dt.tz_convert("Asia/Tokyo").dt.strftime("%Y-%m-%d"))
    positions = []
    days = []
    for signal_date, signal in signals.iterrows():
        next_pos = jp_dates.searchsorted(signal_date, side="right")
        if next_pos >= len(jp_dates):
            continue
        execution = jp_dates[next_pos]
        execution_day = execution.date().isoformat()
        if execution_day not in covered_days:
            continue
        sig = signal.dropna()
        longs = sig[sig >= sig.quantile(1 - q)].index
        shorts = sig[sig <= sig.quantile(q)].index
        selected = [(ticker, 1) for ticker in longs] + [(ticker, -1) for ticker in shorts if ticker not in longs]
        day_rows = []
        for ticker, direction in selected:
            opening = jp_open.at[execution, ticker]
            close = jp_close.at[execution, ticker]
            bar = bar_lookup.get((ticker, execution_day))
            if pd.isna(opening) or pd.isna(close) or opening <= 0 or close <= 0:
                status = "missing_daily_price"
            elif bar is None or pd.isna(bar.open) or bar.open <= 0:
                status = "missing_postopen_bar"
            else:
                status = "observed_proxy"
            row = {
                "signal_date": signal_date.date().isoformat(),
                "execution_date": execution_day,
                "ticker": ticker,
                "side": "LONG" if direction == 1 else "SHORT",
                "status": status,
                "opening_price": float(opening) if pd.notna(opening) else "",
                "postopen_bar_jst": bar.jst.isoformat() if bar is not None else "",
                "postopen_bar_open": float(bar.open) if bar is not None else "",
                "daily_close": float(close) if pd.notna(close) else "",
                "same_open_gross_bps": direction * (close / opening - 1) * 10_000 if status == "observed_proxy" else "",
                "postopen_proxy_gross_bps": direction * (close / bar.open - 1) * 10_000 if status == "observed_proxy" else "",
            }
            positions.append(row)
            day_rows.append(row)
        complete = bool(day_rows) and all(row["status"] == "observed_proxy" for row in day_rows)
        complete_open = ""
        complete_delayed = ""
        if complete and longs.size and shorts.size:
            complete_open = (
                sum(row["same_open_gross_bps"] for row in day_rows if row["side"] == "LONG") / len(longs)
                + sum(row["same_open_gross_bps"] for row in day_rows if row["side"] == "SHORT") / len(shorts)
            )
            complete_delayed = (
                sum(row["postopen_proxy_gross_bps"] for row in day_rows if row["side"] == "LONG") / len(longs)
                + sum(row["postopen_proxy_gross_bps"] for row in day_rows if row["side"] == "SHORT") / len(shorts)
            )
        days.append({
            "signal_date": signal_date.date().isoformat(),
            "execution_date": execution_day,
            "selected_positions": len(day_rows),
            "observed_positions": sum(row["status"] == "observed_proxy" for row in day_rows),
            "complete": complete,
            "same_open_gross_bps": complete_open,
            "postopen_proxy_gross_bps": complete_delayed,
        })
    return positions, days


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--intraday-db", type=Path, default=Path("data/intraday/prices.sqlite"))
    parser.add_argument("--snapshot-dir", type=Path, default=None)
    parser.add_argument("--start", default="2018-07-01")
    parser.add_argument("--end", default="2026-09-19", help="Exclusive date")
    parser.add_argument("--out", type=Path, default=Path("/tmp/juslag_recent_repricing.csv"))
    args = parser.parse_args()
    cache = PriceCache(args.db)
    us = cache.load(list(US_TICKERS), args.start, args.end, "adjusted")
    jp = cache.load(list(JP_TICKERS), args.start, args.end, "adjusted")
    raw = cache.load(list(JP_TICKERS), args.start, args.end, "raw")
    if set(us) != set(US_TICKERS) or set(jp) != set(JP_TICKERS) or set(raw) != set(JP_TICKERS):
        raise SystemExit("Missing cached daily prices")
    us_close = pd.DataFrame({ticker: us[ticker]["close"] for ticker in US_TICKERS})
    jp_adjusted_open = pd.DataFrame({ticker: jp[ticker]["open"] for ticker in JP_TICKERS})
    jp_adjusted_close = pd.DataFrame({ticker: jp[ticker]["close"] for ticker in JP_TICKERS})
    jp_adjusted_open, jp_adjusted_close = repair_known_bad_prices(jp_adjusted_open, jp_adjusted_close)
    jp_raw_open = pd.DataFrame({ticker: raw[ticker]["open"] for ticker in JP_TICKERS})
    jp_raw_close = pd.DataFrame({ticker: raw[ticker]["close"] for ticker in JP_TICKERS})
    jp_raw_open, jp_raw_close = repair_known_bad_prices(jp_raw_open, jp_raw_close)
    us_cc, _, jp_cc = compute_returns(us_close, jp_adjusted_close, jp_adjusted_open)
    joint, _ = build_joint_cc(us_cc, jp_cc, fill_policy="strict", price_mode="adjusted")
    prior = joint.loc[:"2021-12-31"]
    v0 = build_prior_eigenvectors(list(US_TICKERS), list(JP_TICKERS), US_CYCLICAL, JP_CYCLICAL)
    c0 = build_prior_exposure(prior, v0)
    signals = generate_signals(us_cc, jp_cc, c0, l=60, k=3, lam=0.9)
    intraday = (load_intraday_bars(snapshot_dir=args.snapshot_dir) if args.snapshot_dir
                else load_intraday_bars(db=args.intraday_db))
    if intraday.empty:
        raise SystemExit("No intraday observations")
    positions, days = reprice_signals(signals, jp_raw_open, jp_raw_close, intraday)
    if not positions:
        raise SystemExit("No overlapping signal and intraday days")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(positions[0]))
        writer.writeheader()
        writer.writerows(positions)
    print(f"signal_days={len(days)} complete_days={sum(day['complete'] for day in days)} "
          f"positions={len(positions)} observed={sum(row['status'] == 'observed_proxy' for row in positions)}")
    for day in days:
        print(day)
    print(f"out={args.out}")


if __name__ == "__main__":
    main()
