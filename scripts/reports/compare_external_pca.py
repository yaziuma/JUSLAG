"""Compare the independent PCA reproduction with JUSLAG on one local price snapshot."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

from juslag.cache import DEFAULT_DB_PATH, PriceCache
from juslag.config import JP_CYCLICAL, US_CYCLICAL
from juslag.data_loader import repair_known_bad_prices
from juslag.portfolio import build_portfolio_returns_detail
from juslag.prior import build_prior_eigenvectors, build_prior_exposure
from juslag.signal import generate_signals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-repo", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--start", default="2018-07-01")
    parser.add_argument("--end", default="2026-09-17")
    parser.add_argument("--pretrain-end", default="2021-12-31")
    parser.add_argument("--eval-start", default="2022-01-01")
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    args = parser.parse_args()

    sys.path.insert(0, str(args.external_repo / "src"))
    from leadlag.config import DEFAULT  # noqa: PLC0415
    from leadlag.data import Panels  # noqa: PLC0415
    from leadlag.strategy import run_backtest  # noqa: PLC0415
    from leadlag.subspace import PriorModel  # noqa: PLC0415

    cfg = replace(DEFAULT, start=args.start, end=args.end,
                  cfull_start=args.start, cfull_end=args.pretrain_end)
    cache = PriceCache(args.db)
    frames = cache.load(cfg.all_tickers, args.start, args.end, price_mode="adjusted")
    if set(frames) != set(cfg.all_tickers):
        raise SystemExit(f"Missing tickers: {sorted(set(cfg.all_tickers) - set(frames))}")

    close = pd.DataFrame({t: frames[t]["close"] for t in cfg.all_tickers}).sort_index()
    open_ = pd.DataFrame({t: frames[t]["open"] for t in cfg.all_tickers}).sort_index()
    open_, close = repair_known_bad_prices(open_, close)
    common = close["XLK"].dropna().index.intersection(close["1617.T"].dropna().index)
    panels = Panels(cfg, open_.loc[common], close.loc[common])
    pretrain = panels.cc.loc[args.start:args.pretrain_end]
    prior = PriorModel.fit(cfg, pretrain.corr())
    external_returns, turnover = run_backtest(panels, cfg, prior, return_turnover=True)
    external = external_returns["PCA_SUB"].loc[args.eval_start:]

    us_cc, jp_cc = panels.cc_us, panels.cc_jp
    v0 = build_prior_eigenvectors(cfg.us_tickers, cfg.jp_tickers, US_CYCLICAL, JP_CYCLICAL)
    c0 = build_prior_exposure(pretrain.dropna(), v0)
    signals = generate_signals(us_cc, jp_cc, c0, l=cfg.L, k=cfg.K, lam=cfg.lam)
    detail = build_portfolio_returns_detail(
        signals, panels.oc, q=cfg.q,
        min_long_signal=-1e9, max_short_signal=1e9,
    )
    # JUSLAG stores signal dates; the external strategy stores execution dates.
    next_day = dict(zip(common[:-1], common[1:]))
    juslag = detail["gross_return"].rename(index=next_day).loc[args.eval_start:]
    paired = pd.concat([external.rename("external"), juslag.rename("juslag")], axis=1).dropna()
    daily_cost = 4 * args.slippage_bps / 10_000
    delta = paired["external"] - paired["juslag"]
    out = {
        "external_repo": str(args.external_repo),
        "price_mode": "adjusted; same repaired local cache and common-day panel",
        "evaluation_start": args.eval_start,
        "evaluation_end": str(common.max().date()),
        "cost_model": f"flat intraday round trip, {args.slippage_bps}bps/side x gross 2",
        "n_external": len(external),
        "n_juslag": len(juslag),
        "n_paired": len(paired),
        "external_gross_ar_pct": round(float(external.mean() * 252 * 100), 3),
        "juslag_gross_ar_pct": round(float(juslag.mean() * 252 * 100), 3),
        "external_net_ar_pct": round(float((external.mean() - daily_cost) * 252 * 100), 3),
        "juslag_net_ar_pct": round(float((juslag.mean() - daily_cost) * 252 * 100), 3),
        "paired_mean_abs_diff_bps": round(float(delta.abs().mean() * 10_000), 4),
        "paired_max_abs_diff_bps": round(float(delta.abs().max() * 10_000), 4),
        "paired_equal_days": int((delta.abs() < 1e-10).sum()),
        "external_mean_turnover_delta_w": round(float(turnover["PCA_SUB"].loc[args.eval_start:].mean()), 4),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
