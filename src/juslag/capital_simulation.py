from __future__ import annotations

import math

import pandas as pd


def simulate_capital_paths(
    returns: pd.Series,
    *,
    initial_capital_yen: float = 1_000_000,
    fixed_notional_yen: float | None = None,
    strategy_name: str = "strategy",
    return_basis: str = "net_after_tax",
) -> dict[str, object]:
    """Compare reinvested capital with constant-notional P&L on identical returns."""
    if not math.isfinite(initial_capital_yen) or initial_capital_yen <= 0:
        raise ValueError("initial_capital_yen must be positive and finite")
    fixed_notional = initial_capital_yen if fixed_notional_yen is None else fixed_notional_yen
    if not math.isfinite(fixed_notional) or fixed_notional <= 0:
        raise ValueError("fixed_notional_yen must be positive and finite")

    clean = returns.fillna(0.0).astype(float)
    if (~clean.map(math.isfinite)).any():
        raise ValueError("returns must be finite")

    compound = initial_capital_yen * (1.0 + clean).cumprod()
    fixed = initial_capital_yen + fixed_notional * clean.cumsum()
    compound_dd = compound / compound.cummax().clip(lower=initial_capital_yen) - 1.0
    fixed_dd = fixed / fixed.cummax().clip(lower=initial_capital_yen) - 1.0

    return {
        "schema_version": 1,
        "strategy_name": strategy_name,
        "return_basis": return_basis,
        "initial_capital_yen": round(initial_capital_yen, 2),
        "fixed_notional_yen": round(fixed_notional, 2),
        "dates": [pd.Timestamp(day).date().isoformat() for day in clean.index],
        "returns": clean.round(10).tolist(),
        "compound_capital_yen": compound.round(2).tolist(),
        "fixed_capital_yen": fixed.round(2).tolist(),
        "summary": {
            "periods": len(clean),
            "compound_final_yen": round(float(compound.iloc[-1]), 2) if len(compound) else initial_capital_yen,
            "fixed_final_yen": round(float(fixed.iloc[-1]), 2) if len(fixed) else initial_capital_yen,
            "compound_max_drawdown_pct": round(float(compound_dd.min() * 100), 4) if len(compound_dd) else 0.0,
            "fixed_max_drawdown_pct": round(float(fixed_dd.min() * 100), 4) if len(fixed_dd) else 0.0,
        },
        "fixed_model_note": "Each period applies the return to a constant notional; funding constraints are not modeled.",
    }
