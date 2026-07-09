from __future__ import annotations

import pandas as pd

from juslag.config import ExecutionCostConfig
from juslag.portfolio import build_portfolio_returns_detail


def _sample_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    idx = pd.date_range("2024-01-01", periods=6, freq="B")
    sig = pd.DataFrame(
        {
            "A": [0.9, 0.8, 0.7, 0.4, 0.3, 0.2],
            "B": [-0.7, -0.6, -0.5, -0.4, -0.2, -0.1],
            "C": [0.3, 0.4, 0.5, 0.6, 0.8, 0.9],
            "D": [-0.3, -0.2, -0.1, 0.1, 0.2, 0.3],
        },
        index=idx,
    )
    jp_oc = pd.DataFrame(
        {
            "A": [0.01, 0.02, 0.01, 0.01, 0.0, 0.0],
            "B": [-0.01, -0.02, -0.01, -0.01, 0.0, 0.0],
            "C": [0.005, 0.004, 0.006, 0.003, 0.0, 0.0],
            "D": [-0.005, -0.004, -0.006, -0.003, 0.0, 0.0],
        },
        index=idx,
    )
    return sig, jp_oc


def test_costs_reduce_returns() -> None:
    sig, jp_oc = _sample_data()
    detail = build_portfolio_returns_detail(sig, jp_oc, q=0.25, execution_costs=ExecutionCostConfig())

    assert (detail["net_pre_tax_return"] <= detail["gross_return"] + 1e-12).all()
    assert detail["commission_cost"].sum() > 0
    assert detail["slippage_cost"].sum() > 0
    assert detail["borrow_cost"].sum() > 0


def test_no_short_has_zero_borrow() -> None:
    sig, jp_oc = _sample_data()
    detail = build_portfolio_returns_detail(
        sig,
        jp_oc,
        q=0.25,
        execution_costs=ExecutionCostConfig(allow_short=False),
    )

    assert (detail["n_short"] == 0).all()
    assert detail["borrow_cost"].sum() == 0


def test_allow_short_false_removes_short_side() -> None:
    sig, jp_oc = _sample_data()
    detail_on = build_portfolio_returns_detail(sig, jp_oc, q=0.25, execution_costs=ExecutionCostConfig(allow_short=True))
    detail_off = build_portfolio_returns_detail(sig, jp_oc, q=0.25, execution_costs=ExecutionCostConfig(allow_short=False))

    assert detail_on["short_notional"].sum() > 0
    assert detail_off["short_notional"].sum() == 0
