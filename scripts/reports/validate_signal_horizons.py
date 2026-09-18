"""Offline, out-of-sample horizon study for the paper-aligned PCA signal."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from juslag.cache import DEFAULT_DB_PATH, PriceCache
from juslag.config import JP_CYCLICAL, JP_TICKERS, JP_TRADING_UNITS, US_CYCLICAL, US_TICKERS
from juslag.data_loader import build_joint_cc, compute_returns, repair_known_bad_prices
from juslag.prior import build_prior_eigenvectors, build_prior_exposure
from juslag.signal import generate_signals


def estimate_annual_tax_yen(trades: pd.DataFrame, tax_rate: float = 0.20315) -> float:
    """Tax realized yen P&L by calendar year, with three-year loss carryforward."""
    pnl = trades["capital_after_yen"] - trades["capital_before_yen"]
    years = pd.DatetimeIndex(trades["exit_date"]).year
    yearly = pnl.groupby(years).sum()
    losses: list[tuple[int, float]] = []
    tax_total = 0.0
    for year, gain in yearly.items():
        losses = [(loss_year, amount) for loss_year, amount in losses if year - loss_year <= 3]
        if gain < 0:
            losses.append((int(year), -float(gain)))
            continue
        remaining_gain = float(gain)
        new_losses = []
        for loss_year, amount in losses:
            used = min(amount, remaining_gain)
            remaining_gain -= used
            if amount > used:
                new_losses.append((loss_year, amount - used))
        losses = new_losses
        tax_total += remaining_gain * tax_rate
    return tax_total


def settle_tax_through(state: dict, year: int, tax_rate: float = 0.20315) -> float:
    """Settle realized annual P&L; losses expire after three calendar years."""
    due = 0.0
    for taxable_year in sorted(y for y in state["pending"] if y <= year):
        gain = state["pending"].pop(taxable_year)
        state["losses"] = [(y, amount) for y, amount in state["losses"] if taxable_year - y <= 3]
        if gain < 0:
            state["losses"].append((taxable_year, -gain))
            continue
        remaining = gain
        unused = []
        for loss_year, amount in state["losses"]:
            used = min(amount, remaining)
            remaining -= used
            if amount > used:
                unused.append((loss_year, amount - used))
        state["losses"] = unused
        due += remaining * tax_rate
    state["paid"] += due
    return due


def trading_unit_on(ticker: str, day: pd.Timestamp) -> int:
    if ticker == "1629.T" and day < pd.Timestamp("2026-03-30"):
        return 1
    return JP_TRADING_UNITS.get(ticker, 1)


def execution_nominal_open(raw_open: pd.DataFrame) -> pd.DataFrame:
    """Undo Yahoo's 1629 split adjustment when sizing historical orders."""
    nominal = raw_open.copy()
    if "1629.T" in nominal:
        nominal.loc[nominal.index < "2026-04-01", "1629.T"] *= 500
    return nominal


def simulate_nonoverlap(
    signals: pd.DataFrame,
    jp_open: pd.DataFrame,
    jp_close: pd.DataFrame,
    *,
    start: str,
    end: str,
    horizon: int = 5,
    q: float = 0.3,
    initial_capital_yen: float = 1_000_000,
    slippage_bps_per_side: float = 5.0,
    allow_short: bool = False,
    borrow_rate_annual: float = 0.011,
    nominal_open: pd.DataFrame | None = None,
    tax_state: dict | None = None,
    annual_tax_settlement: bool = False,
) -> pd.DataFrame:
    """One position batch at a time, integer units, fixed gross budget."""
    if horizon < 1 or initial_capital_yen <= 0 or not 0 < q < 0.5:
        raise ValueError("Invalid portfolio parameters")
    dates = jp_open.index.intersection(jp_close.index).sort_values()
    if nominal_open is None:
        nominal_open = jp_open
    capital = float(initial_capital_yen)
    if annual_tax_settlement and tax_state is None:
        tax_state = {"pending": {}, "losses": [], "paid": 0.0}
        settle_final_tax = True
    else:
        settle_final_tax = False
    last_exit = pd.Timestamp.min
    rows: list[dict] = []
    for signal_date, signal in signals.loc[start:end].iterrows():
        if capital <= 0:
            break
        if signal_date < last_exit:
            continue
        entry_pos = dates.searchsorted(signal_date, side="right")
        exit_pos = entry_pos + horizon - 1
        if exit_pos >= len(dates):
            continue
        entry_date, exit_date = dates[entry_pos], dates[exit_pos]
        if exit_date > pd.Timestamp(end):
            continue
        sig = signal.dropna()
        if len(sig) < 3:
            continue
        longs = sig[sig >= sig.quantile(1 - q)].index.tolist()
        shorts = sig[sig <= sig.quantile(q)].index.tolist() if allow_short else []
        if not longs:
            continue
        tax_paid_before = 0.0
        if annual_tax_settlement:
            tax_paid_before = settle_tax_through(tax_state, entry_date.year - 1)
            capital -= tax_paid_before
            if capital <= 0:
                break
        sides = [(t, 1) for t in longs] + [(t, -1) for t in shorts if t not in longs]
        budget_per_side = capital / len(sides)
        gross_pnl = 0.0
        gross_notional = 0.0
        short_notional = 0.0
        traded = 0
        invalid = False
        for ticker, direction in sides:
            entry = nominal_open.at[entry_date, ticker]
            adjusted_entry = jp_open.at[entry_date, ticker]
            if pd.isna(entry) or pd.isna(adjusted_entry) or entry <= 0 or adjusted_entry <= 0:
                invalid = True
                break
            lot = trading_unit_on(ticker, entry_date)
            units = int(budget_per_side // (entry * lot)) * lot
            if units < 1:
                continue
            close = jp_close.at[exit_date, ticker]
            if pd.isna(close) or close <= 0:
                raise ValueError(f"Missing exit price for {ticker} on {exit_date.date()}")
            notional = units * entry
            gross_notional += notional
            short_notional += notional if direction < 0 else 0.0
            gross_pnl += direction * notional * (close / adjusted_entry - 1)
            traded += 1
        if invalid or traded == 0:
            continue
        cost = 2 * gross_notional * slippage_bps_per_side / 10_000
        borrow = short_notional * borrow_rate_annual * horizon / 252
        net_pnl = gross_pnl - cost - borrow
        before = capital
        capital += net_pnl
        if annual_tax_settlement:
            tax_state["pending"][exit_date.year] = tax_state["pending"].get(exit_date.year, 0.0) + net_pnl
        rows.append({
            "signal_date": signal_date,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "capital_before_yen": before,
            "capital_after_yen": capital,
            "gross_notional_yen": gross_notional,
            "short_notional_yen": short_notional,
            "positions": traded,
            "gross_return": gross_pnl / before,
            "net_pre_tax_return": net_pnl / before,
            "tax_paid_before_yen": tax_paid_before,
        })
        last_exit = exit_date
    if rows and settle_final_tax:
        rows[-1]["tax_paid_final_yen"] = settle_tax_through(tax_state, rows[-1]["exit_date"].year)
        rows[-1]["capital_after_yen"] -= rows[-1]["tax_paid_final_yen"]
    return pd.DataFrame(rows)


def summarize_nonoverlap(trades: pd.DataFrame, initial_capital_yen: float) -> dict:
    if trades.empty:
        return {"trades": 0}
    net = pd.Series(trades["net_pre_tax_return"].to_numpy(), index=pd.DatetimeIndex(trades["exit_date"]))
    equity = trades["capital_after_yen"].reset_index(drop=True)
    drawdown = equity / equity.cummax() - 1
    tax_yen = estimate_annual_tax_yen(trades)
    return {
        "trades": len(trades),
        "first_entry": trades["entry_date"].min().date().isoformat(),
        "last_exit": trades["exit_date"].max().date().isoformat(),
        "gross_pnl_yen": round(float((trades["gross_return"] * trades["capital_before_yen"]).sum())),
        "net_pre_tax_pnl_yen": round(float(trades["capital_after_yen"].iloc[-1] - initial_capital_yen)),
        "estimated_tax_yen": round(tax_yen),
        "after_tax_estimate_yen": round(float(equity.iloc[-1] - tax_yen)),
        "max_drawdown_pre_tax_pct": round(float(drawdown.min() * 100), 2),
        "mean_gross_exposure_pct": round(float((trades["gross_notional_yen"] / trades["capital_before_yen"]).mean() * 100), 2),
        "yearly_net_pre_tax_pct": {
            str(year): round(float(((1 + group).prod() - 1) * 100), 2)
            for year, group in net.groupby(net.index.year)
        },
    }


def summarize_after_tax(trades: pd.DataFrame, initial_capital_yen: float, tax_paid_yen: float) -> dict:
    if trades.empty:
        return {"trades": 0, "final_capital_yen": round(initial_capital_yen - tax_paid_yen)}
    equity = trades["capital_after_yen"].reset_index(drop=True)
    drawdown = equity / equity.cummax() - 1
    return {
        "trades": len(trades),
        "final_capital_yen": round(float(equity.iloc[-1])),
        "tax_paid_yen": round(tax_paid_yen),
        "max_drawdown_after_tax_pct": round(float(drawdown.min() * 100), 2),
    }


def walk_forward_nonoverlap(
    signals: pd.DataFrame,
    jp_open: pd.DataFrame,
    jp_close: pd.DataFrame,
    *,
    start: str,
    end: str,
    initial_capital_yen: float,
    slippage_bps_per_side: float,
    allow_short: bool = False,
    horizons: tuple[int, ...] = (1, 2, 3, 5),
    nominal_open: pd.DataFrame | None = None,
    annual_tax_settlement: bool = False,
) -> dict:
    """Select holding period using only prior years, then trade the next year."""
    first_year = pd.Timestamp(start).year
    last_year = pd.Timestamp(end).year
    capital = initial_capital_yen
    tax_state = {"pending": {}, "losses": [], "paid": 0.0} if annual_tax_settlement else None
    folds = []
    all_trades = []
    for year in range(first_year + 1, last_year + 1):
        train_start = f"{max(first_year, year - 2)}-01-01"
        train_end = f"{year - 1}-12-31"
        scores = {}
        for horizon in horizons:
            train = simulate_nonoverlap(
                signals, jp_open, jp_close, start=train_start, end=train_end,
                horizon=horizon, initial_capital_yen=initial_capital_yen,
                slippage_bps_per_side=slippage_bps_per_side, allow_short=allow_short,
                nominal_open=nominal_open,
            )
            if not train.empty:
                scores[horizon] = float(train["capital_after_yen"].iloc[-1])
        if not scores:
            continue
        selected = max(sorted(scores), key=scores.get)
        if annual_tax_settlement:
            capital -= settle_tax_through(tax_state, year - 1)
            if capital <= 0:
                break
        test_start = f"{year}-01-01"
        test_end = min(pd.Timestamp(end), pd.Timestamp(f"{year}-12-31")).date().isoformat()
        test = simulate_nonoverlap(
            signals, jp_open, jp_close, start=test_start, end=test_end,
            horizon=selected, initial_capital_yen=capital,
            slippage_bps_per_side=slippage_bps_per_side, allow_short=allow_short,
            nominal_open=nominal_open,
            tax_state=tax_state, annual_tax_settlement=annual_tax_settlement,
        )
        before = capital
        if not test.empty:
            capital = float(test["capital_after_yen"].iloc[-1])
            all_trades.append(test)
        folds.append({
            "test_year": year,
            "training_start": train_start,
            "training_end": train_end,
            "selected_horizon": selected,
            "test_trades": len(test),
            "net_after_tax_pct" if annual_tax_settlement else "net_pre_tax_pct": round((capital / before - 1) * 100, 2),
        })
    combined = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    if annual_tax_settlement:
        if not combined.empty:
            final_due = settle_tax_through(tax_state, int(combined["exit_date"].iloc[-1].year))
            combined.loc[combined.index[-1], "capital_after_yen"] -= final_due
        return {"folds": folds, "combined": summarize_after_tax(combined, initial_capital_yen, tax_state["paid"])}
    return {"folds": folds, "combined": summarize_nonoverlap(combined, initial_capital_yen)}


def benchmark_same_schedule(
    trades: pd.DataFrame,
    jp_open: pd.DataFrame,
    jp_close: pd.DataFrame,
    *,
    initial_capital_yen: float,
    slippage_bps_per_side: float,
    nominal_open: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Equal-weight JP ETF basket on exactly the strategy's entry/exit dates."""
    capital = initial_capital_yen
    if nominal_open is None:
        nominal_open = jp_open
    rows = []
    for trade in trades.itertuples():
        entry_date, exit_date = trade.entry_date, trade.exit_date
        entry = nominal_open.loc[entry_date]
        adjusted_entry = jp_open.loc[entry_date]
        exit_price = jp_close.loc[exit_date]
        valid = (entry > 0) & entry.notna() & (adjusted_entry > 0) & adjusted_entry.notna()
        selected = entry.index[valid]
        if len(selected) == 0:
            raise ValueError(f"No benchmark prices for {entry_date}")
        if exit_price[selected].isna().any():
            raise ValueError(f"Missing benchmark exit prices for {exit_date}")
        units = pd.Series({
            ticker: int((capital / len(selected)) // (entry[ticker] * trading_unit_on(ticker, entry_date)))
            * trading_unit_on(ticker, entry_date)
            for ticker in selected
        })
        notional = float((units * entry[selected]).sum())
        pnl = float((units * entry[selected] * (exit_price[selected] / adjusted_entry[selected] - 1)).sum())
        net_pnl = pnl - 2 * notional * slippage_bps_per_side / 10_000
        before = capital
        capital += net_pnl
        rows.append({
            "signal_date": trade.signal_date,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "capital_before_yen": before,
            "capital_after_yen": capital,
            "gross_notional_yen": notional,
            "short_notional_yen": 0.0,
            "positions": int((units > 0).sum()),
            "gross_return": pnl / before,
            "net_pre_tax_return": net_pnl / before,
        })
    return pd.DataFrame(rows)


def exposure_matched_sector_comparison(
    trades: pd.DataFrame, jp_open: pd.DataFrame, jp_close: pd.DataFrame,
) -> dict:
    """Compare realized selected-basket returns with all-sector returns on the same notional."""
    if trades.empty:
        return {"trades": 0}
    records = []
    for trade in trades.itertuples():
        entry = jp_open.loc[trade.entry_date]
        exit_price = jp_close.loc[trade.exit_date]
        if entry.isna().any() or exit_price.isna().any() or (entry <= 0).any():
            raise ValueError(f"Missing sector control prices on {trade.entry_date}")
        sector_return = float((exit_price / entry - 1).mean())
        selected_return = float(trade.gross_return * trade.capital_before_yen / trade.gross_notional_yen)
        records.append({
            "exit_date": trade.exit_date,
            "selected_return": selected_return,
            "sector_return": sector_return,
            "excess_return": selected_return - sector_return,
            "excess_yen": trade.gross_notional_yen * (selected_return - sector_return),
        })
    paired = pd.DataFrame(records)
    excess = paired["excess_return"].to_numpy()
    centered = excess - excess.mean()
    n = len(excess)
    long_run_variance = float(np.dot(centered, centered) / n)
    for lag in range(1, min(4, n - 1) + 1):
        autocov = float(np.dot(centered[lag:], centered[:-lag]) / n)
        long_run_variance += 2 * (1 - lag / 5) * autocov
    se = np.sqrt(max(0.0, long_run_variance) / n)
    return {
        "trades": n,
        "selected_mean_gross_bps_on_notional": round(float(paired["selected_return"].mean() * 10_000), 2),
        "sector_mean_gross_bps_on_same_notional": round(float(paired["sector_return"].mean() * 10_000), 2),
        "mean_paired_excess_bps": round(float(excess.mean() * 10_000), 2),
        "paired_excess_yen_on_actual_notional": round(float(paired["excess_yen"].sum())),
        "positive_excess_pct": round(float((excess > 0).mean() * 100), 1),
        "descriptive_hac95_mean_excess_bps": [
            round(float((excess.mean() - 1.96 * se) * 10_000), 2),
            round(float((excess.mean() + 1.96 * se) * 10_000), 2),
        ],
        "annual_mean_excess_bps": {
            str(year): round(float(group.mean() * 10_000), 2)
            for year, group in paired.groupby(pd.DatetimeIndex(paired["exit_date"]).year)["excess_return"]
        },
    }


def permutation_benchmark(
    signals: pd.DataFrame,
    jp_open: pd.DataFrame,
    jp_close: pd.DataFrame,
    *,
    nominal_open: pd.DataFrame,
    start: str,
    end: str,
    initial_capital_yen: float,
    slippage_bps_per_side: float,
    repetitions: int = 100,
    seed: int = 20260918,
) -> dict:
    """Shuffle each day's sector scores, preserving score distribution and cost model."""
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    actual = simulate_nonoverlap(
        signals, jp_open, jp_close, nominal_open=nominal_open, start=start, end=end,
        initial_capital_yen=initial_capital_yen, slippage_bps_per_side=slippage_bps_per_side,
    )
    if actual.empty:
        raise ValueError("No actual trades to compare")
    actual_final = float(actual["capital_after_yen"].iloc[-1])
    rng = np.random.default_rng(seed)
    final_capitals = []
    exposures = []
    for _ in range(repetitions):
        shuffled = pd.DataFrame(rng.permuted(signals.to_numpy(), axis=1),
                                index=signals.index, columns=signals.columns)
        trades = simulate_nonoverlap(
            shuffled, jp_open, jp_close, nominal_open=nominal_open, start=start, end=end,
            initial_capital_yen=initial_capital_yen, slippage_bps_per_side=slippage_bps_per_side,
        )
        final_capitals.append(float(trades["capital_after_yen"].iloc[-1]))
        exposures.append(float((trades["gross_notional_yen"] / trades["capital_before_yen"]).mean()))
    return {
        "repetitions": repetitions,
        "actual_final_yen": round(actual_final),
        "random_median_final_yen": round(float(np.median(final_capitals))),
        "random_p05_final_yen": round(float(np.quantile(final_capitals, 0.05))),
        "random_p95_final_yen": round(float(np.quantile(final_capitals, 0.95))),
        "random_mean_exposure_pct": round(float(np.mean(exposures) * 100), 2),
        "one_sided_empirical_p": round((1 + sum(value >= actual_final for value in final_capitals)) / (repetitions + 1), 4),
    }


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
    parser.add_argument("--nonoverlap", action="store_true", help="Run fixed-capital, nonoverlapping 5-session portfolio")
    parser.add_argument("--capital-yen", type=float, default=1_000_000)
    parser.add_argument("--permutations", type=int, default=0,
                        help="Matched random-score portfolios (0 disables)")
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
    output = {
        "mode": args.mode,
        "eval_start": args.eval_start,
        "pretrain_end": args.pretrain_end,
        "joint_rows": quality["joint_rows"],
        "last_signal": signals.index.max().date().isoformat(),
        "slippage_bps_per_side": args.slippage_bps,
        "horizons": summary,
    }
    if args.nonoverlap:
        if args.mode != "adjusted":
            raise SystemExit("Nonoverlap portfolio requires adjusted returns and raw nominal prices")
        jp_raw = cache.load(list(JP_TICKERS), args.start, args.end, "raw")
        if set(jp_raw) != set(JP_TICKERS):
            raise SystemExit("Missing raw JP prices for nominal order sizing")
        raw_open = pd.concat([jp_raw[t]["open"].rename(t) for t in JP_TICKERS], axis=1)
        raw_close = pd.concat([jp_raw[t]["close"].rename(t) for t in JP_TICKERS], axis=1)
        raw_open, _ = repair_known_bad_prices(raw_open, raw_close)
        nominal_open = execution_nominal_open(raw_open)
        portfolio = {}
        for label, allow_short in (("long_only", False), ("optimistic_short", True)):
            portfolio[label] = {}
            for slippage in sorted({args.slippage_bps, 10.0, 20.0}):
                trades = simulate_nonoverlap(signals, jp_open, jp_close, start=args.eval_start,
                                             end=args.end, initial_capital_yen=args.capital_yen,
                                             slippage_bps_per_side=slippage, allow_short=allow_short,
                                             nominal_open=nominal_open)
                portfolio[label][f"{slippage:g}bps_per_side"] = summarize_nonoverlap(trades, args.capital_yen)
        output["nonoverlap_5_session"] = portfolio
        after_tax_trades = simulate_nonoverlap(
            signals, jp_open, jp_close, start=args.eval_start, end=args.end,
            initial_capital_yen=args.capital_yen, slippage_bps_per_side=args.slippage_bps,
            nominal_open=nominal_open, annual_tax_settlement=True,
        )
        output["long_only_annual_tax_reinvestment"] = summarize_after_tax(
            after_tax_trades, args.capital_yen,
            float(after_tax_trades.get("tax_paid_before_yen", pd.Series(dtype=float)).sum())
            + float(after_tax_trades.get("tax_paid_final_yen", pd.Series(dtype=float)).sum()),
        )
        output["walk_forward"] = {
            label: walk_forward_nonoverlap(
                signals, jp_open, jp_close, start=args.eval_start, end=args.end,
                initial_capital_yen=args.capital_yen,
                slippage_bps_per_side=args.slippage_bps, allow_short=allow_short,
                nominal_open=nominal_open,
            ) for label, allow_short in (("long_only", False), ("optimistic_short", True))
        }
        output["walk_forward_long_only_annual_tax_reinvestment"] = walk_forward_nonoverlap(
            signals, jp_open, jp_close, start=args.eval_start, end=args.end,
            initial_capital_yen=args.capital_yen, slippage_bps_per_side=args.slippage_bps,
            nominal_open=nominal_open, annual_tax_settlement=True,
        )
        fixed_long_trades = simulate_nonoverlap(
            signals, jp_open, jp_close, start=args.eval_start, end=args.end,
            initial_capital_yen=args.capital_yen,
            slippage_bps_per_side=args.slippage_bps, nominal_open=nominal_open,
        )
        output["same_notional_sector_equal_weight_comparison"] = exposure_matched_sector_comparison(
            fixed_long_trades, jp_open, jp_close,
        )
        output["same_schedule_equal_weight_jp_benchmark"] = summarize_nonoverlap(
            benchmark_same_schedule(fixed_long_trades, jp_open, jp_close,
                                    initial_capital_yen=args.capital_yen,
                                    slippage_bps_per_side=args.slippage_bps,
                                    nominal_open=nominal_open),
            args.capital_yen,
        )
        if args.permutations:
            output["score_permutation_benchmark"] = permutation_benchmark(
                signals, jp_open, jp_close, nominal_open=nominal_open,
                start=args.eval_start, end=args.end, initial_capital_yen=args.capital_yen,
                slippage_bps_per_side=args.slippage_bps, repetitions=args.permutations,
            )
        output["portfolio_limitations"] = "Exploratory: prior horizon selection used the same sample; short inventory, spread and actual fills unobserved."
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
