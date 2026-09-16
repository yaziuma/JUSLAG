"""Offline, out-of-sample horizon study for the paper-aligned PCA signal."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from juslag.cache import DEFAULT_DB_PATH, PriceCache
from juslag.config import JP_CYCLICAL, JP_TICKERS, US_CYCLICAL, US_TICKERS
from juslag.data_loader import build_joint_cc, compute_returns, repair_known_bad_prices
from juslag.prior import build_prior_eigenvectors, build_prior_exposure
from juslag.signal import generate_signals


def measure_horizons(
    signals: pd.DataFrame,
    jp_open: pd.DataFrame,
    jp_close: pd.DataFrame,
    *,
    start: str,
    end: str,
    horizons: tuple[int, ...] = (1, 2, 3, 5),
    q: float = 0.3,
    slippage_bps_per_side: float = 5.0,
    max_abs_ticker_return: float = 0.30,
) -> dict:
    """Measure close-day signals against the first subsequent JP open, never same-day JP prices."""
    dates = jp_open.index.intersection(jp_close.index).sort_values()
    records: dict[int, list[dict]] = {h: [] for h in horizons}
    anomalies: dict[int, list[dict]] = {h: [] for h in horizons}
    for signal_date, signal in signals.loc[start:end].iterrows():
        pos = dates.searchsorted(signal_date, side="right")
        if pos >= len(dates):
            continue
        sig = signal.dropna()
        if len(sig) < 3:
            continue
        longs = sig >= sig.quantile(1 - q)
        shorts = sig <= sig.quantile(q)
        if not longs.any() or not shorts.any():
            continue
        for horizon in horizons:
            if pos + horizon - 1 >= len(dates):
                continue
            entry = jp_open.loc[dates[pos], sig.index]
            close = jp_close.loc[dates[pos + horizon - 1], sig.index]
            valid = entry.notna() & close.notna() & (entry > 0)
            if not valid.all():
                continue
            returns = close / entry - 1
            extreme = returns[returns.abs() > max_abs_ticker_return]
            if not extreme.empty:
                anomalies[horizon].append({
                    "signal_date": signal_date.date().isoformat(),
                    "entry_date": dates[pos].date().isoformat(),
                    "exit_date": dates[pos + horizon - 1].date().isoformat(),
                    "ticker": str(extreme.abs().idxmax()),
                    "return_pct": round(float(extreme.loc[extreme.abs().idxmax()] * 100), 2),
                })
                continue
            gross = float(returns[longs].mean() - returns[shorts].mean())
            # Gross notional is 2: both sides enter and exit once per holding period.
            round_trip_cost = 4 * slippage_bps_per_side / 10_000
            records[horizon].append({
                "signal_date": signal_date,
                "entry_date": dates[pos],
                "exit_date": dates[pos + horizon - 1],
                "gross": gross,
                "net": gross - round_trip_cost,
                "rank_ic": float(sig.corr(returns, method="spearman")),
            })

    result = {}
    for horizon, rows in records.items():
        df = pd.DataFrame(rows)
        if df.empty:
            result[str(horizon)] = {"n": 0}
            continue
        result[str(horizon)] = {
            "n": len(df),
            "excluded_anomaly_windows": len(anomalies[horizon]),
            "anomaly_examples": anomalies[horizon][:3],
            "first_entry": df["entry_date"].min().date().isoformat(),
            "last_exit": df["exit_date"].max().date().isoformat(),
            "gross_mean_bps": round(float(df["gross"].mean() * 10_000), 2),
            "net_mean_bps": round(float(df["net"].mean() * 10_000), 2),
            "mean_rank_ic": round(float(df["rank_ic"].mean()), 4),
            "positive_gross_pct": round(float((df["gross"] > 0).mean() * 100), 1),
            "positive_net_pct": round(float((df["net"] > 0).mean() * 100), 1),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--start", default="2018-07-01")
    parser.add_argument("--end", default="2026-09-17")
    parser.add_argument("--pretrain-end", default="2021-12-31")
    parser.add_argument("--eval-start", default="2022-01-01")
    parser.add_argument("--mode", choices=("raw", "adjusted"), default="adjusted")
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--max-abs-ticker-return", type=float, default=0.30)
    args = parser.parse_args()

    cache = PriceCache(args.db)
    us = cache.load(list(US_TICKERS), args.start, args.end, args.mode)
    jp = cache.load(list(JP_TICKERS), args.start, args.end, args.mode)
    missing = sorted((set(US_TICKERS) - us.keys()) | (set(JP_TICKERS) - jp.keys()))
    if missing:
        raise SystemExit(f"Missing cached tickers: {missing}")
    us_close = pd.concat([us[t]["close"].rename(t) for t in US_TICKERS], axis=1)
    jp_open = pd.concat([jp[t]["open"].rename(t) for t in JP_TICKERS], axis=1)
    jp_close = pd.concat([jp[t]["close"].rename(t) for t in JP_TICKERS], axis=1)
    jp_open, jp_close = repair_known_bad_prices(jp_open, jp_close)
    us_cc, _, jp_cc = compute_returns(us_close, jp_close, jp_open)
    joint, quality = build_joint_cc(us_cc, jp_cc, fill_policy="strict", price_mode=args.mode)
    v0 = build_prior_eigenvectors(list(US_TICKERS), list(JP_TICKERS), US_CYCLICAL, JP_CYCLICAL)
    pretrain = joint.loc[:args.pretrain_end]
    if pretrain.empty:
        raise SystemExit("No pretraining rows")
    c0 = build_prior_exposure(pretrain, v0)
    signals = generate_signals(us_cc, jp_cc, c0, l=60, k=3, lam=0.9)
    summary = measure_horizons(
        signals, jp_open, jp_close,
        start=args.eval_start, end=args.end,
        slippage_bps_per_side=args.slippage_bps,
        max_abs_ticker_return=args.max_abs_ticker_return,
    )
    print(json.dumps({
        "mode": args.mode,
        "eval_start": args.eval_start,
        "pretrain_end": args.pretrain_end,
        "joint_rows": quality["joint_rows"],
        "last_signal": signals.index.max().date().isoformat(),
        "slippage_bps_per_side": args.slippage_bps,
        "horizons": summary,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
