from __future__ import annotations

import pandas as pd

from juslag.config import ExecutionCostConfig

BUSINESS_DAYS_PER_YEAR = 252


def _apply_short_constraints(
    short_mask: pd.Series,
    allow_short: bool,
    short_constraint_mode: str,
    unshortable_tickers: tuple[str, ...],
) -> pd.Series:
    if not allow_short:
        return pd.Series(False, index=short_mask.index)
    if short_constraint_mode == "exclude_unshortable" and unshortable_tickers:
        blocked = set(unshortable_tickers)
        return short_mask & ~short_mask.index.to_series().isin(blocked)
    return short_mask


def build_portfolio_returns_detail(
    signal_df: pd.DataFrame,
    jp_oc: pd.DataFrame,
    q: float = 0.3,
    execution_costs: ExecutionCostConfig | None = None,
    min_long_signal: float = 0.0,
    max_short_signal: float = 0.0,
) -> pd.DataFrame:
    """Build equal-weight long/short returns with cost breakdown per day."""
    cfg = execution_costs or ExecutionCostConfig()
    jp_oc_aligned = jp_oc.shift(-1)
    rows: list[dict[str, object]] = []

    borrow_rate_daily = cfg.short_borrow_rate_annual / BUSINESS_DAYS_PER_YEAR

    for t in signal_df.index:
        if t not in jp_oc_aligned.index:
            continue
        sig = signal_df.loc[t].dropna()
        ret = jp_oc_aligned.loc[t, sig.index].dropna()
        common = sig.index.intersection(ret.index)
        if len(common) < 3:
            continue

        sig_c = sig[common]
        ret_c = ret[common]

        lo = sig_c.quantile(q)
        hi = sig_c.quantile(1.0 - q)

        long_mask = (sig_c >= hi) & (sig_c >= min_long_signal)
        short_mask = (sig_c <= lo) & (sig_c <= max_short_signal)
        short_mask = _apply_short_constraints(
            short_mask,
            allow_short=cfg.allow_short,
            short_constraint_mode=cfg.short_constraint_mode,
            unshortable_tickers=cfg.unshortable_tickers,
        )

        if long_mask.sum() == 0:
            continue

        w_long = 1.0 / long_mask.sum()
        long_notional = float(long_mask.sum() * abs(w_long))
        long_gross = float((ret_c[long_mask] * w_long).sum())

        short_notional = 0.0
        short_gross = 0.0
        if short_mask.sum() > 0:
            w_short = -1.0 / short_mask.sum()
            short_notional = float(short_mask.sum() * abs(w_short))
            short_gross = float((ret_c[short_mask] * w_short).sum())

        gross_return = long_gross + short_gross
        slippage_cost = (cfg.slippage_bps_per_side / 10_000.0) * 2 * (long_notional + short_notional)
        # keep explicit separation from commission
        commission_cost = (cfg.commission_bps_per_side / 10_000.0) * 2 * (long_notional + short_notional)
        borrow_cost = borrow_rate_daily * short_notional
        net_pre_tax_return = gross_return - commission_cost - slippage_cost - borrow_cost

        rows.append(
            {
                "date": t,
                "gross_return": gross_return,
                "commission_cost": commission_cost,
                "slippage_cost": slippage_cost,
                "borrow_cost": borrow_cost,
                "net_pre_tax_return": net_pre_tax_return,
                "long_notional": long_notional,
                "short_notional": short_notional,
                "n_long": int(long_mask.sum()),
                "n_short": int(short_mask.sum()),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "gross_return",
                "commission_cost",
                "slippage_cost",
                "borrow_cost",
                "net_pre_tax_return",
                "long_notional",
                "short_notional",
                "n_long",
                "n_short",
            ]
        )

    return pd.DataFrame(rows).set_index("date")


def build_portfolio(
    signal_df: pd.DataFrame,
    jp_oc: pd.DataFrame,
    q: float = 0.3,
    execution_costs: ExecutionCostConfig | None = None,
    min_long_signal: float = 0.0,
    max_short_signal: float = 0.0,
) -> pd.Series:
    """Backward-compatible API returning pre-tax net returns as Series."""
    detail = build_portfolio_returns_detail(signal_df, jp_oc, q=q, execution_costs=execution_costs, min_long_signal=min_long_signal, max_short_signal=max_short_signal)
    if detail.empty:
        return pd.Series(dtype=float)
    return detail["net_pre_tax_return"]


def build_portfolio_with_strategy_rule(
    signal_df: "pd.DataFrame",
    jp_oc: "pd.DataFrame",
    overnight_gap_df: "pd.DataFrame",
    regime_df: "pd.DataFrame | None",
    rule: "object",  # StrategyRule — 循環インポート回避
    q: float = 0.3,
    execution_costs: "ExecutionCostConfig | None" = None,
    min_long_signal: float = 0.0,
    max_short_signal: float = 0.0,
    gap_threshold: float = 0.005,
) -> "pd.DataFrame":
    """Strategy-rule-filtered backtest.

    各日に StrategyContext を構築して rule.decide() を呼び、
    決定に応じてポジションを変更した上で損益を計算する。
    """
    from juslag.strategies.context import StrategyContext

    cfg = execution_costs or ExecutionCostConfig()
    jp_oc_aligned = jp_oc.shift(-1)
    borrow_rate_daily = cfg.short_borrow_rate_annual / BUSINESS_DAYS_PER_YEAR
    rows: list[dict[str, object]] = []

    for t in signal_df.index:
        if t not in jp_oc_aligned.index:
            continue
        sig = signal_df.loc[t].dropna()
        ret_next = jp_oc_aligned.loc[t, sig.index].dropna()
        common = sig.index.intersection(ret_next.index)
        if len(common) < 3:
            continue

        sig_c = sig[common]
        ret_c = ret_next[common]
        lo = sig_c.quantile(q)
        hi = sig_c.quantile(1.0 - q)

        # overnight_gap for this date
        gap_t = overnight_gap_df.loc[t] if t in overnight_gap_df.index else pd.Series(dtype=float)
        open_gap = float(gap_t.mean()) if not gap_t.empty else None

        long_cands = sig_c.index[sig_c >= hi].tolist()
        short_cands = sig_c.index[sig_c <= lo].tolist()
        long_gap = (
            float(gap_t.reindex(long_cands).dropna().mean())
            if long_cands and not gap_t.empty else None
        )
        short_gap = (
            float(gap_t.reindex(short_cands).dropna().mean())
            if short_cands and not gap_t.empty else None
        )

        # regime from regime_df
        trend_regime = vol_regime = rotation_regime = None
        if regime_df is not None and t in regime_df.index:
            row_r = regime_df.loc[t]
            trend_regime = str(row_r.get("trend_regime", "")) or None
            vol_regime = str(row_r.get("vol_regime", "")) or None
            rotation_regime = str(row_r.get("rotation_regime", "")) or None

        ctx = StrategyContext(
            signal_date=t.date().isoformat(),
            candidate_signal_strength=None,
            open_gap=open_gap,
            long_gap=long_gap,
            short_gap=short_gap,
            trend_regime=trend_regime,
            vol_regime=vol_regime,
            rotation_regime=rotation_regime,
        )
        decision = rule.decide(ctx)

        if decision.action == "skip":
            continue

        # Base masks
        long_mask = (sig_c >= hi) & (sig_c >= min_long_signal)
        short_mask = (sig_c <= lo) & (sig_c <= max_short_signal)
        # quantile-only short mask (max_short_signal フィルタなし) — strategy override 用
        short_mask_quantile = sig_c <= lo
        short_mask = _apply_short_constraints(
            short_mask,
            allow_short=cfg.allow_short,
            short_constraint_mode=cfg.short_constraint_mode,
            unshortable_tickers=cfg.unshortable_tickers,
        )
        short_mask_quantile = _apply_short_constraints(
            short_mask_quantile,
            allow_short=cfg.allow_short,
            short_constraint_mode=cfg.short_constraint_mode,
            unshortable_tickers=cfg.unshortable_tickers,
        )

        strategy = decision.selected_strategy
        if strategy == "long_flip_oc":
            new_short = long_mask | short_mask
            long_mask = pd.Series(False, index=sig_c.index)
            short_mask = new_short
        elif strategy == "short_only_oc":
            long_mask = pd.Series(False, index=sig_c.index)
            # max_short_signal フィルタを無視して quantile ベースの short を使う
            short_mask = short_mask_quantile
        elif strategy in ("gap_ovht_oc", "lgap_oc") and not gap_t.empty:
            for ticker in sig_c.index[long_mask].tolist():
                if ticker in gap_t.index and float(gap_t[ticker]) > gap_threshold:
                    long_mask[ticker] = False
            if strategy == "gap_ovht_oc":
                for ticker in sig_c.index[short_mask].tolist():
                    if ticker in gap_t.index and float(gap_t[ticker]) < -gap_threshold:
                        short_mask[ticker] = False

        # long_flip_oc / short_only_oc は long がゼロでも short があれば取引する
        if long_mask.sum() == 0 and short_mask.sum() == 0:
            continue
        if long_mask.sum() == 0 and strategy not in ("long_flip_oc", "short_only_oc"):
            continue

        if long_mask.sum() > 0:
            w_long = 1.0 / long_mask.sum()
            long_notional = float(long_mask.sum() * abs(w_long))
            long_gross = float((ret_c[long_mask] * w_long).sum())
        else:
            long_notional = 0.0
            long_gross = 0.0

        short_notional = 0.0
        short_gross = 0.0
        if short_mask.sum() > 0:
            w_short = -1.0 / short_mask.sum()
            short_notional = float(short_mask.sum() * abs(w_short))
            short_gross = float((ret_c[short_mask] * w_short).sum())

        gross_return = long_gross + short_gross
        slippage_cost = (cfg.slippage_bps_per_side / 10_000.0) * 2 * (long_notional + short_notional)
        commission_cost = (cfg.commission_bps_per_side / 10_000.0) * 2 * (long_notional + short_notional)
        borrow_cost = borrow_rate_daily * short_notional
        net_return = gross_return - commission_cost - slippage_cost - borrow_cost

        rows.append({
            "date": t,
            "gross_return": gross_return,
            "commission_cost": commission_cost,
            "slippage_cost": slippage_cost,
            "borrow_cost": borrow_cost,
            "net_pre_tax_return": net_return,
            "long_notional": long_notional,
            "short_notional": short_notional,
            "n_long": int(long_mask.sum()),
            "n_short": int(short_mask.sum()),
            "strategy_decision": decision.selected_strategy,
        })

    if not rows:
        _empty_cols = [
            "gross_return", "commission_cost", "slippage_cost", "borrow_cost",
            "net_pre_tax_return", "long_notional", "short_notional", "n_long", "n_short", "strategy_decision",
        ]
        return pd.DataFrame(columns=_empty_cols)

    return pd.DataFrame(rows).set_index("date")
