"""Compare paper-style PCA P&L with market-first versus common-day-first returns."""
from __future__ import annotations

import argparse
import json

import pandas as pd

from juslag.cache import DEFAULT_DB_PATH, PriceCache
from juslag.config import JP_CYCLICAL, JP_TICKERS, US_CYCLICAL, US_TICKERS
from juslag.data_loader import repair_known_bad_prices
from juslag.portfolio import build_portfolio_returns_detail
from juslag.prior import build_prior_eigenvectors, build_prior_exposure
from juslag.signal import generate_signals


def paired_pca_returns(
    close: pd.DataFrame,
    open_: pd.DataFrame,
    us: list[str],
    jp: list[str],
    pretrain_end: str,
    eval_start: str,
) -> pd.DataFrame:
    """Hold price panel, prior, signal dates and fills fixed; vary only return ordering."""
    common = close[us[0]].dropna().index.intersection(close[jp[0]].dropna().index)
    common_close = close.loc[common, us + jp]
    common_cc = common_close.pct_change(fill_method=None)
    market_cc = pd.concat([
        close[us].dropna(how="all").pct_change(fill_method=None).reindex(common),
        close[jp].dropna(how="all").pct_change(fill_method=None).reindex(common),
    ], axis=1)
    # Identical fully observed rows prevent availability/drop rules from changing the sample.
    valid = common_cc.notna().all(axis=1) & market_cc.notna().all(axis=1)
    common_cc = common_cc.loc[valid]
    market_cc = market_cc.loc[valid]
    v0 = build_prior_eigenvectors(us, jp, US_CYCLICAL, JP_CYCLICAL)
    prior = build_prior_exposure(common_cc.loc[:pretrain_end], v0)
    jp_oc = close.loc[common, jp] / open_.loc[common, jp] - 1.0
    next_day = dict(zip(common[:-1], common[1:]))

    def returns(cc: pd.DataFrame) -> pd.Series:
        signals = generate_signals(cc[us], cc[jp], prior, l=60, k=3, lam=0.9)
        detail = build_portfolio_returns_detail(
            signals, jp_oc, q=0.3, min_long_signal=-1e9, max_short_signal=1e9,
        )
        return detail["gross_return"].rename(index=next_day)

    paired = pd.concat({"common_first": returns(common_cc), "market_first": returns(market_cc)}, axis=1)
    return paired.loc[eval_start:].dropna()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--start", default="2018-07-01")
    parser.add_argument("--end", default="2026-09-17")
    parser.add_argument("--pretrain-end", default="2021-12-31")
    parser.add_argument("--eval-start", default="2022-01-01")
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    args = parser.parse_args()
    us, jp = list(US_TICKERS), list(JP_TICKERS)
    tickers = us + jp
    frames = PriceCache(args.db).load(tickers, args.start, args.end, price_mode="adjusted")
    if set(frames) != set(tickers):
        raise SystemExit(f"Missing tickers: {sorted(set(tickers) - set(frames))}")
    close = pd.DataFrame({ticker: frames[ticker]["close"] for ticker in tickers}).sort_index()
    open_ = pd.DataFrame({ticker: frames[ticker]["open"] for ticker in tickers}).sort_index()
    open_, close = repair_known_bad_prices(open_, close)
    paired = paired_pca_returns(close, open_, us, jp, args.pretrain_end, args.eval_start)
    delta = paired["market_first"] - paired["common_first"]
    cost = 4 * args.slippage_bps / 10_000
    print(json.dumps({
        "evaluation_start": args.eval_start,
        "evaluation_end": str(paired.index.max().date()),
        "paired_days": len(paired),
        "common_first_gross_ar_pct": round(float(paired["common_first"].mean() * 252 * 100), 3),
        "market_first_gross_ar_pct": round(float(paired["market_first"].mean() * 252 * 100), 3),
        "common_first_net_ar_pct": round(float((paired["common_first"].mean() - cost) * 252 * 100), 3),
        "market_first_net_ar_pct": round(float((paired["market_first"].mean() - cost) * 252 * 100), 3),
        "market_minus_common_gross_ar_points": round(float(delta.mean() * 252 * 100), 3),
        "different_pnl_days": int(delta.abs().gt(1e-10).sum()),
        "mean_abs_daily_pnl_diff_bps": round(float(delta.abs().mean() * 10_000), 3),
        "max_abs_daily_pnl_diff_bps": round(float(delta.abs().max() * 10_000), 3),
    }, indent=2))


if __name__ == "__main__":
    main()
