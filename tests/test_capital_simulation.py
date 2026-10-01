from __future__ import annotations

import pandas as pd
import pytest

from juslag.capital_simulation import simulate_capital_paths


def test_compound_and_fixed_notional_use_identical_return_stream() -> None:
    returns = pd.Series(
        [0.10, -0.10], index=pd.to_datetime(["2026-01-05", "2026-01-06"])
    )

    result = simulate_capital_paths(
        returns, initial_capital_yen=1_000, fixed_notional_yen=1_000,
        strategy_name="test",
    )

    assert result["compound_capital_yen"] == [1100.0, 990.0]
    assert result["fixed_capital_yen"] == [1100.0, 1000.0]
    assert result["summary"]["compound_final_yen"] == 990.0
    assert result["summary"]["fixed_final_yen"] == 1000.0
    assert result["dates"] == ["2026-01-05", "2026-01-06"]


def test_fixed_notional_can_differ_from_initial_capital() -> None:
    returns = pd.Series([0.10], index=pd.to_datetime(["2026-01-05"]))

    result = simulate_capital_paths(
        returns, initial_capital_yen=1_000, fixed_notional_yen=500,
    )

    assert result["compound_capital_yen"] == [1100.0]
    assert result["fixed_capital_yen"] == [1050.0]


@pytest.mark.parametrize("value", [0, -1, float("inf")])
def test_invalid_capital_is_rejected(value: float) -> None:
    returns = pd.Series(dtype=float)
    with pytest.raises(ValueError):
        simulate_capital_paths(returns, initial_capital_yen=value)
