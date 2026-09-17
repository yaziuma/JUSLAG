"""Compare paper-style PCA P&L with market-first versus common-day-first returns."""
from __future__ import annotations

import argparse
import json

import pandas as pd

from juslag.cache import DEFAULT_DB_PATH, PriceCache
from juslag.config import JP_CYCLICAL, JP_TICKERS, US_CYCLICAL, US_TICKERS
from juslag.data_loader import build_joint_cc, compute_returns, repair_known_bad_prices
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


def paired_execution_returns(
    close: pd.DataFrame,
    open_: pd.DataFrame,
    us: list[str],
    jp: list[str],
    pretrain_end: str,
    eval_start: str,
) -> tuple[pd.DataFrame, int]:
    """Use identical market-first signals, varying only the next execution session."""
    common = close[us[0]].dropna().index.intersection(close[jp[0]].dropna().index)
    market_cc = pd.concat([
        close[us].dropna(how="all").pct_change(fill_method=None).reindex(common),
        close[jp].dropna(how="all").pct_change(fill_method=None).reindex(common),
    ], axis=1).dropna()
    common_cc = close.loc[common, us + jp].pct_change(fill_method=None)
    valid = common_cc.notna().all(axis=1) & market_cc.reindex(common).notna().all(axis=1)
    common_cc = common_cc.loc[valid]
    market_cc = market_cc.loc[valid]
    v0 = build_prior_eigenvectors(us, jp, US_CYCLICAL, JP_CYCLICAL)
    prior = build_prior_exposure(common_cc.loc[:pretrain_end], v0)
    signals = generate_signals(market_cc[us], market_cc[jp], prior, l=60, k=3, lam=0.9)
    jp_days = close[jp].dropna(how="all").index
    oc = close.loc[jp_days, jp] / open_.loc[jp_days, jp] - 1.0

    def returns(jp_oc: pd.DataFrame) -> pd.Series:
        detail = build_portfolio_returns_detail(
            signals, jp_oc, q=0.3, min_long_signal=-1e9, max_short_signal=1e9,
        )
        return detail["gross_return"]

    paired = pd.concat({
        "next_common": returns(oc.loc[common]),
        "next_jp": returns(oc),
    }, axis=1).loc[eval_start:].dropna()
    common_pos = common.searchsorted(paired.index, side="right")
    jp_pos = jp_days.searchsorted(paired.index, side="right")
    usable = (common_pos < len(common)) & (jp_pos < len(jp_days))
    mismatch = int((common[common_pos[usable]] != jp_days[jp_pos[usable]]).sum())
    return paired, mismatch


def production_paper_returns(
    close: pd.DataFrame,
    open_: pd.DataFrame,
    us: list[str],
    jp: list[str],
    pretrain_end: str,
    eval_start: str,
) -> pd.Series:
    """Mirror the production paper branch using local prices and no network fetch."""
    us_close = close[us].dropna(how="all")
    jp_close = close[jp].dropna(how="all")
    jp_open = open_[jp].dropna(how="all")
    us_cc, jp_oc, jp_cc = compute_returns(us_close, jp_close, jp_open)
    joint_cc, _ = build_joint_cc(us_cc, jp_cc)
    v0 = build_prior_eigenvectors(us, jp, US_CYCLICAL, JP_CYCLICAL)
    prior = build_prior_exposure(joint_cc.loc[:pretrain_end], v0)
    signals = generate_signals(us_cc, jp_cc, prior, l=60, k=3, lam=0.9)
    detail = build_portfolio_returns_detail(
        signals.loc[eval_start:], jp_oc.loc[eval_start:],
        q=0.3, min_long_signal=-1e9, max_short_signal=1e9,
    )
    return detail["gross_return"]


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
    execution, mismatch = paired_execution_returns(close, open_, us, jp, args.pretrain_end, args.eval_start)
    execution_delta = execution["next_jp"] - execution["next_common"]
    production = production_paper_returns(close, open_, us, jp, args.pretrain_end, args.eval_start)
    production_paired = pd.concat({"fixed_panel": execution["next_jp"], "production": production}, axis=1).dropna()
    production_delta = production_paired["production"] - production_paired["fixed_panel"]
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
        "execution_calendar": {
            "paired_signal_days": len(execution),
            "different_execution_dates": mismatch,
            "next_common_gross_ar_pct": round(float(execution["next_common"].mean() * 252 * 100), 3),
            "next_jp_gross_ar_pct": round(float(execution["next_jp"].mean() * 252 * 100), 3),
            "next_jp_minus_common_ar_points": round(float(execution_delta.mean() * 252 * 100), 3),
            "different_pnl_days": int(execution_delta.abs().gt(1e-10).sum()),
        },
        "production_reconciliation": {
            "production_days": len(production),
            "production_gross_ar_pct": round(float(production.mean() * 252 * 100), 3),
            "paired_signal_days": len(production_paired),
            "production_minus_fixed_panel_ar_points": round(float(production_delta.mean() * 252 * 100), 3),
            "different_pnl_days": int(production_delta.abs().gt(1e-10).sum()),
            "mean_abs_daily_pnl_diff_bps": round(float(production_delta.abs().mean() * 10_000), 3),
            "production_only_signal_days": len(production.index.difference(execution.index)),
            "production_only_signal_dates": [str(d.date()) for d in production.index.difference(execution.index)],
            "fixed_panel_only_signal_days": len(execution.index.difference(production.index)),
        },
    }, indent=2))


if __name__ == "__main__":
    main()
