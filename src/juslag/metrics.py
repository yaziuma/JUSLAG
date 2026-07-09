from __future__ import annotations

import numpy as np
import pandas as pd

from juslag.config import TaxConfig


def compute_performance(returns: pd.Series, label: str = "Strategy") -> dict[str, float | int | str]:
    """Compute annualized metrics from daily returns (252 business days/year)."""
    r = returns.dropna()
    if len(r) == 0:
        return {
            "Strategy": label,
            "AR(%)": np.nan,
            "Risk(%)": np.nan,
            "R/R": np.nan,
            "MDD(%)": np.nan,
            "N_days": 0,
        }

    ann_ret = r.mean() * 252
    ann_risk = r.std() * np.sqrt(252)
    rr = ann_ret / ann_risk if ann_risk > 0 else np.nan

    cumret = (1 + r).cumprod()
    roll_max = cumret.cummax()
    drawdown = cumret / roll_max - 1
    mdd = drawdown.min()

    return {
        "Strategy": label,
        "AR(%)": round(ann_ret * 100, 2),
        "Risk(%)": round(ann_risk * 100, 2),
        "R/R": round(rr, 3),
        "MDD(%)": round(mdd * 100, 2),
        "N_days": len(r),
    }


def _apply_daily_positive_only_tax(returns: pd.Series, tax_rate: float) -> tuple[pd.Series, pd.Series]:
    tax = returns.clip(lower=0.0) * tax_rate
    return returns - tax, tax


def _apply_annual_net_tax(
    returns: pd.Series,
    tax_rate: float,
    loss_carryforward_years: int,
) -> tuple[pd.Series, pd.Series]:
    net_after_tax = returns.copy()
    tax_series = pd.Series(0.0, index=returns.index)
    carry_losses: list[tuple[int, float]] = []

    for year in sorted(returns.index.year.unique()):
        year_mask = returns.index.year == year
        year_returns = returns[year_mask]
        year_pnl = float(year_returns.sum())

        carry_losses = [(y, loss) for y, loss in carry_losses if year - y <= loss_carryforward_years and loss > 0]
        available_loss = sum(loss for _, loss in carry_losses)

        taxable_profit = max(0.0, year_pnl - available_loss)
        tax_amount = taxable_profit * tax_rate

        if year_pnl > 0 and tax_amount > 0:
            year_end = year_returns.index[-1]
            net_after_tax.loc[year_end] -= tax_amount
            tax_series.loc[year_end] = tax_amount

        remaining_profit = max(0.0, year_pnl)
        updated_losses: list[tuple[int, float]] = []
        for loss_year, loss_amt in carry_losses:
            used = min(loss_amt, remaining_profit)
            remaining_profit -= used
            remaining = loss_amt - used
            if remaining > 0:
                updated_losses.append((loss_year, remaining))

        if year_pnl < 0:
            updated_losses.append((year, abs(year_pnl)))
        carry_losses = updated_losses

    return net_after_tax, tax_series


def apply_tax_model(returns: pd.Series, tax_config: TaxConfig | None = None) -> pd.DataFrame:
    cfg = tax_config or TaxConfig()
    r = returns.fillna(0.0)

    if not cfg.enabled:
        tax_paid = pd.Series(0.0, index=r.index)
        return pd.DataFrame({"net_after_tax_return": r, "tax_paid": tax_paid}, index=r.index)

    if cfg.tax_model == "daily_positive_only":
        net_after_tax, tax_paid = _apply_daily_positive_only_tax(r, cfg.tax_rate)
    elif cfg.tax_model == "annual_net":
        net_after_tax, tax_paid = _apply_annual_net_tax(r, cfg.tax_rate, cfg.loss_carryforward_years)
    else:
        raise ValueError(f"Unsupported tax model: {cfg.tax_model}")

    return pd.DataFrame({"net_after_tax_return": net_after_tax, "tax_paid": tax_paid}, index=r.index)


def compute_yearly_tax_adjusted_returns(returns: pd.Series, tax_config: TaxConfig | None = None) -> pd.DataFrame:
    """Return yearly pre-tax / tax / after-tax totals for inspection."""
    tax_df = apply_tax_model(returns, tax_config)
    yearly = pd.DataFrame(
        {
            "pre_tax": returns.groupby(returns.index.year).sum(),
            "tax_paid": tax_df["tax_paid"].groupby(tax_df.index.year).sum(),
        }
    )
    yearly["after_tax"] = yearly["pre_tax"] - yearly["tax_paid"]
    yearly.index.name = "year"
    return yearly
