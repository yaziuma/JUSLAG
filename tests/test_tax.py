from __future__ import annotations

import pandas as pd

from juslag.config import TaxConfig
from juslag.metrics import apply_tax_model


def test_annual_net_taxes_profitable_year() -> None:
    idx = pd.to_datetime(["2024-01-10", "2024-01-11", "2024-12-30"])
    returns = pd.Series([0.01, -0.002, 0.005], index=idx)
    out = apply_tax_model(returns, TaxConfig(enabled=True, tax_rate=0.2, tax_model="annual_net", loss_carryforward_years=3))

    assert out["tax_paid"].sum() > 0
    assert out.loc[pd.Timestamp("2024-12-30"), "tax_paid"] > 0


def test_annual_net_no_tax_for_loss_year() -> None:
    idx = pd.to_datetime(["2024-01-10", "2024-01-11"])
    returns = pd.Series([-0.01, -0.002], index=idx)
    out = apply_tax_model(returns, TaxConfig(enabled=True, tax_rate=0.2, tax_model="annual_net", loss_carryforward_years=3))

    assert out["tax_paid"].sum() == 0


def test_carryforward_reduces_future_tax() -> None:
    idx = pd.to_datetime(["2024-12-30", "2025-12-30"])
    returns = pd.Series([-0.10, 0.08], index=idx)
    out = apply_tax_model(returns, TaxConfig(enabled=True, tax_rate=0.2, tax_model="annual_net", loss_carryforward_years=3))

    assert out["tax_paid"].sum() == 0


def test_daily_positive_only_differs_from_annual_net() -> None:
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-12-30"])
    returns = pd.Series([0.02, -0.01, 0.005], index=idx)

    annual = apply_tax_model(returns, TaxConfig(enabled=True, tax_rate=0.2, tax_model="annual_net", loss_carryforward_years=3))
    daily = apply_tax_model(returns, TaxConfig(enabled=True, tax_rate=0.2, tax_model="daily_positive_only", loss_carryforward_years=3))

    assert annual["tax_paid"].sum() != daily["tax_paid"].sum()
