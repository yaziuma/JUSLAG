from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/reports/validate_signal_horizons.py"
SPEC = spec_from_file_location("validate_signal_horizons", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_production_assumptions_come_from_manual_strategy_config() -> None:
    config = {
        "strategy_id": "v2",
        "signal_model": {
            "window_l": 60, "k_factors": 3, "lambda_reg": 0.9,
            "selection_quantile": 0.2,
        },
        "portfolio": {
            "initial_capital_yen": 1_000_000, "deployment_fraction": 0.9,
            "long_only": True, "nonoverlapping_batches": True,
        },
        "execution": {
            "holding_jpx_sessions": 5, "assumed_slippage_bps_per_side": 5,
        },
    }

    assumptions = MODULE.production_assumptions(config)

    assert assumptions["strategy_id"] == "v2"
    assert assumptions["selection_quantile"] == 0.2
    assert assumptions["deployment_fraction"] == 0.9
    assert assumptions["holding_sessions"] == 5
    assert assumptions["slippage_bps_per_side"] == 5


def test_production_assumptions_reject_strategy_shape_drift() -> None:
    config = {
        "strategy_id": "drifted",
        "signal_model": {
            "window_l": 60, "k_factors": 3, "lambda_reg": 0.9,
            "selection_quantile": 0.2,
        },
        "portfolio": {
            "initial_capital_yen": 1_000_000, "deployment_fraction": 0.9,
            "long_only": True, "nonoverlapping_batches": True,
        },
        "execution": {
            "holding_jpx_sessions": 4, "assumed_slippage_bps_per_side": 5,
        },
    }

    with pytest.raises(ValueError, match="5-session"):
        MODULE.production_assumptions(config)


def test_nonoverlap_limits_capital_and_skips_overlapping_signals() -> None:
    dates = pd.date_range("2025-01-01", periods=8)
    signals = pd.DataFrame(
        [[3.0, 2.0, 1.0]] * 5,
        index=dates[:5], columns=["A", "B", "C"],
    )
    opens = pd.DataFrame(100.0, index=dates, columns=signals.columns)
    closes = opens.copy()
    closes.loc[dates[3], "A"] = 110.0
    closes.loc[dates[3], "C"] = 90.0

    trades = MODULE.simulate_nonoverlap(
        signals, opens, closes, start="2025-01-01", end="2025-01-08",
        horizon=3, initial_capital_yen=1_000, slippage_bps_per_side=0,
    )

    assert trades.iloc[0]["signal_date"] == dates[0]
    assert trades.iloc[0]["entry_date"] == dates[1]
    assert trades.iloc[0]["exit_date"] == dates[3]
    assert trades.iloc[0]["gross_notional_yen"] <= 1_000
    assert trades.iloc[0]["capital_after_yen"] == 1_100
    assert dates[1] not in set(trades["signal_date"])
    assert dates[2] not in set(trades["signal_date"])


def test_nonoverlap_matches_production_ninety_percent_deployment() -> None:
    dates = pd.date_range("2025-01-01", periods=3)
    signals = pd.DataFrame(
        [[3.0, 2.0, 1.0]], index=dates[:1], columns=["A", "B", "C"]
    )
    opens = pd.DataFrame(100.0, index=dates, columns=signals.columns)
    closes = opens.copy()
    closes.loc[dates[1], "A"] = 110.0

    trades = MODULE.simulate_nonoverlap(
        signals, opens, closes, start="2025-01-01", end="2025-01-03",
        horizon=1, initial_capital_yen=1_000, slippage_bps_per_side=0,
        deployment_fraction=0.90,
    )

    assert trades.iloc[0]["gross_notional_yen"] == 900
    assert trades.iloc[0]["capital_after_yen"] == 1_090


def test_nonoverlap_sizes_before_open_from_prior_close() -> None:
    dates = pd.date_range("2025-01-01", periods=3)
    signals = pd.DataFrame(
        [[3.0, 2.0, 1.0]], index=dates[:1], columns=["A", "B", "C"]
    )
    opens = pd.DataFrame(110.0, index=dates, columns=signals.columns)
    closes = opens.copy()
    closes.loc[dates[1], "A"] = 121.0
    sizing = pd.DataFrame(100.0, index=dates, columns=signals.columns)

    trades = MODULE.simulate_nonoverlap(
        signals, opens, closes, start="2025-01-01", end="2025-01-03",
        horizon=1, initial_capital_yen=1_000, slippage_bps_per_side=0,
        deployment_fraction=0.90, nominal_open=opens, sizing_prices=sizing,
    )

    # Nine units are fixed from the observable 100-yen prior close. The
    # realized 110-yen open controls actual notional and P&L.
    assert trades.iloc[0]["gross_notional_yen"] == 990
    assert trades.iloc[0]["capital_after_yen"] == 1_099


def test_nonoverlap_can_measure_delayed_entry_fallback() -> None:
    dates = pd.date_range("2025-01-01", periods=6)
    signals = pd.DataFrame(
        [[3.0, 2.0, 1.0]], index=dates[:1], columns=["A", "B", "C"]
    )
    opens = pd.DataFrame(100.0, index=dates, columns=signals.columns)
    closes = opens.copy()
    closes.loc[dates[2], "A"] = 110.0

    trades = MODULE.simulate_nonoverlap(
        signals, opens, closes, start="2025-01-01", end="2025-01-06",
        horizon=1, initial_capital_yen=1_000, slippage_bps_per_side=0,
        entry_delay_sessions=1,
    )

    assert trades.iloc[0]["entry_date"] == dates[2]
    assert trades.iloc[0]["exit_date"] == dates[2]
    assert trades.iloc[0]["capital_after_yen"] == 1_100


def test_nonoverlap_rejects_negative_entry_delay() -> None:
    dates = pd.date_range("2025-01-01", periods=3)
    signals = pd.DataFrame([[3.0, 2.0, 1.0]], index=dates[:1], columns=["A", "B", "C"])
    prices = pd.DataFrame(100.0, index=dates, columns=signals.columns)

    with pytest.raises(ValueError, match="Invalid portfolio parameters"):
        MODULE.simulate_nonoverlap(
            signals, prices, prices, start="2025-01-01", end="2025-01-03",
            entry_delay_sessions=-1,
        )


def test_short_scenario_charges_borrow_and_slippage() -> None:
    dates = pd.date_range("2025-01-01", periods=4)
    signals = pd.DataFrame([[3.0, 2.0, 1.0]], index=dates[:1], columns=["A", "B", "C"])
    prices = pd.DataFrame(100.0, index=dates, columns=signals.columns)

    trades = MODULE.simulate_nonoverlap(
        signals, prices, prices, start="2025-01-01", end="2025-01-04",
        horizon=2, initial_capital_yen=1_000, allow_short=True,
        slippage_bps_per_side=10, borrow_rate_annual=0.252,
    )

    assert trades.iloc[0]["short_notional_yen"] == 500
    assert trades.iloc[0]["gross_notional_yen"] == 1_000
    assert round(trades.iloc[0]["capital_after_yen"], 6) == 997.0


def test_walk_forward_selection_does_not_read_test_year_returns() -> None:
    dates = pd.DatetimeIndex([f"{year}-01-{day:02d}" for year in (2022, 2023) for day in range(3, 9)])
    signals = pd.DataFrame([[3.0, 2.0, 1.0]] * len(dates), index=dates, columns=["A", "B", "C"])
    opens = pd.DataFrame(100.0, index=dates, columns=signals.columns)
    closes = opens.copy()
    changed = closes.copy()
    changed.loc["2023", "A"] = 150.0

    first = MODULE.walk_forward_nonoverlap(
        signals, opens, closes, start="2022-01-01", end="2023-12-31",
        initial_capital_yen=1_000, slippage_bps_per_side=0, horizons=(1, 2),
    )
    second = MODULE.walk_forward_nonoverlap(
        signals, opens, changed, start="2022-01-01", end="2023-12-31",
        initial_capital_yen=1_000, slippage_bps_per_side=0, horizons=(1, 2),
    )

    assert first["folds"][0]["selected_horizon"] == second["folds"][0]["selected_horizon"]


def test_walk_forward_quantile_selection_does_not_read_test_year_returns() -> None:
    dates = pd.DatetimeIndex([f"{year}-01-{day:02d}" for year in (2022, 2023) for day in range(3, 12)])
    signals = pd.DataFrame(
        [[5.0, 4.0, 3.0, 2.0, 1.0]] * len(dates),
        index=dates,
        columns=["A", "B", "C", "D", "E"],
    )
    opens = pd.DataFrame(100.0, index=dates, columns=signals.columns)
    closes = opens.copy()
    changed = closes.copy()
    changed.loc["2023", "A"] = 150.0

    kwargs = dict(
        start="2022-01-01", end="2023-12-31", initial_capital_yen=1_000,
        slippage_bps_per_side=0, quantiles=(0.2, 0.4), horizon=1,
    )
    first = MODULE.walk_forward_quantile_nonoverlap(signals, opens, closes, **kwargs)
    second = MODULE.walk_forward_quantile_nonoverlap(signals, opens, changed, **kwargs)

    assert first["folds"][0]["selected_quantile"] == second["folds"][0]["selected_quantile"]


def test_equal_weight_benchmark_uses_same_trade_schedule() -> None:
    dates = pd.date_range("2025-01-01", periods=4)
    prices = pd.DataFrame(100.0, index=dates, columns=["A", "B"])
    closes = prices.copy()
    closes.loc[dates[2], "A"] = 110.0
    trades = pd.DataFrame([{"signal_date": dates[0], "entry_date": dates[1], "exit_date": dates[2]}])

    result = MODULE.benchmark_same_schedule(
        trades, prices, closes, initial_capital_yen=1_000, slippage_bps_per_side=0,
    )

    assert result.iloc[0]["gross_notional_yen"] == 1_000
    assert result.iloc[0]["capital_after_yen"] == 1_050


def test_sector_comparison_matches_trade_notional_and_schedule() -> None:
    dates = pd.date_range("2025-01-01", periods=3)
    opens = pd.DataFrame(100.0, index=dates, columns=["A", "B"])
    closes = opens.copy()
    closes.loc[dates[2], "A"] = 120.0
    trades = pd.DataFrame([{
        "entry_date": dates[1], "exit_date": dates[2],
        "capital_before_yen": 1_000.0, "gross_notional_yen": 500.0,
        "gross_return": 0.1,
    }])

    comparison = MODULE.exposure_matched_sector_comparison(trades, opens, closes)

    assert comparison["selected_mean_gross_bps_on_notional"] == 2000
    assert comparison["sector_mean_gross_bps_on_same_notional"] == 1000
    assert comparison["mean_paired_excess_bps"] == 1000
    assert comparison["paired_excess_yen_on_actual_notional"] == 50


def test_sector_comparison_refuses_missing_control_price() -> None:
    dates = pd.date_range("2025-01-01", periods=3)
    opens = pd.DataFrame(100.0, index=dates, columns=["A", "B"])
    closes = opens.copy()
    closes.loc[dates[2], "B"] = float("nan")
    trades = pd.DataFrame([{
        "entry_date": dates[1], "exit_date": dates[2],
        "capital_before_yen": 1_000.0, "gross_notional_yen": 500.0,
        "gross_return": 0.1,
    }])

    with pytest.raises(ValueError, match="Missing sector control prices"):
        MODULE.exposure_matched_sector_comparison(trades, opens, closes)


def test_1629_trades_only_in_ten_unit_lots() -> None:
    dates = pd.date_range("2026-04-02", periods=3)
    signals = pd.DataFrame([[3.0, 2.0, 1.0]], index=dates[:1], columns=["1629.T", "A", "B"])
    opens = pd.DataFrame(100.0, index=dates, columns=signals.columns)
    closes = opens.copy()
    closes.loc[dates[1], "1629.T"] = 110.0

    trades = MODULE.simulate_nonoverlap(
        signals, opens, closes, start="2026-04-02", end="2026-04-04",
        horizon=1, initial_capital_yen=900, slippage_bps_per_side=0,
    )

    assert trades.empty


def test_1629_historical_nominal_price_and_lot_change() -> None:
    raw = pd.DataFrame({"1629.T": [200.0, 200.0, 200.0]},
                       index=pd.DatetimeIndex(["2026-03-27", "2026-03-30", "2026-04-01"]))
    nominal = MODULE.execution_nominal_open(raw)

    assert nominal["1629.T"].tolist() == [100_000.0, 100_000.0, 200.0]
    assert MODULE.trading_unit_on("1629.T", pd.Timestamp("2026-03-27")) == 1
    assert MODULE.trading_unit_on("1629.T", pd.Timestamp("2026-03-30")) == 10


def test_nominal_price_controls_affordability_but_adjusted_price_controls_return() -> None:
    dates = pd.date_range("2025-01-01", periods=3)
    signals = pd.DataFrame([[3.0, 2.0, 1.0]], index=dates[:1], columns=["1629.T", "A", "B"])
    adjusted_open = pd.DataFrame(200.0, index=dates, columns=signals.columns)
    adjusted_close = adjusted_open.copy()
    adjusted_close.loc[dates[1], "1629.T"] = 220.0
    nominal = adjusted_open.copy()
    nominal["1629.T"] *= 500

    trades = MODULE.simulate_nonoverlap(
        signals, adjusted_open, adjusted_close, start="2025-01-01", end="2025-01-03",
        horizon=1, initial_capital_yen=1_000_000, slippage_bps_per_side=0,
        nominal_open=nominal,
    )

    assert trades.iloc[0]["gross_notional_yen"] == 1_000_000
    assert trades.iloc[0]["capital_after_yen"] == 1_100_000


def test_missing_exit_price_fails_instead_of_skipping_loss() -> None:
    dates = pd.date_range("2025-01-01", periods=3)
    signals = pd.DataFrame([[3.0, 2.0, 1.0]], index=dates[:1], columns=["A", "B", "C"])
    opens = pd.DataFrame(100.0, index=dates, columns=signals.columns)
    closes = opens.copy()
    closes.loc[dates[1], "A"] = float("nan")

    with pytest.raises(ValueError, match="Missing exit price"):
        MODULE.simulate_nonoverlap(
            signals, opens, closes, start="2025-01-01", end="2025-01-03",
            horizon=1, initial_capital_yen=1_000,
        )


def test_annual_tax_uses_realized_yen_and_loss_carry() -> None:
    trades = pd.DataFrame([
        {"exit_date": pd.Timestamp("2022-12-30"), "capital_before_yen": 1_000, "capital_after_yen": 900},
        {"exit_date": pd.Timestamp("2023-12-29"), "capital_before_yen": 900, "capital_after_yen": 950},
        {"exit_date": pd.Timestamp("2024-12-30"), "capital_before_yen": 950, "capital_after_yen": 1_100},
    ])

    assert MODULE.estimate_annual_tax_yen(trades, tax_rate=0.2) == 20


def test_annual_tax_reduces_next_year_order_size() -> None:
    dates = pd.DatetimeIndex(["2024-12-27", "2024-12-30", "2025-01-06", "2025-01-07"])
    signals = pd.DataFrame([[3.0, 2.0, 1.0], [3.0, 2.0, 1.0]],
                           index=dates[[0, 2]], columns=["A", "B", "C"])
    opens = pd.DataFrame(10.0, index=dates, columns=signals.columns)
    closes = opens.copy()
    closes.loc[dates[1], "A"] = 20.0
    gross = MODULE.simulate_nonoverlap(signals, opens, closes, start="2024-12-27",
                                       end="2025-01-07", horizon=1,
                                       initial_capital_yen=100, slippage_bps_per_side=0)
    taxed = MODULE.simulate_nonoverlap(signals, opens, closes, start="2024-12-27",
                                       end="2025-01-07", horizon=1,
                                       initial_capital_yen=100, slippage_bps_per_side=0,
                                       annual_tax_settlement=True)
    assert gross.iloc[1]["gross_notional_yen"] == 200
    assert taxed.iloc[1]["tax_paid_before_yen"] == pytest.approx(20.315)
    assert taxed.iloc[1]["gross_notional_yen"] == 170
    assert taxed.iloc[-1]["capital_after_yen"] == pytest.approx(179.685)


def test_loss_carry_is_applied_before_next_year_sizing() -> None:
    state = {"pending": {2022: -100.0, 2023: 50.0, 2024: 150.0}, "losses": [], "paid": 0.0}
    assert MODULE.settle_tax_through(state, 2023, tax_rate=0.2) == 0
    assert MODULE.settle_tax_through(state, 2024, tax_rate=0.2) == 20
    assert state["paid"] == 20


def test_permutation_benchmark_is_reproducible() -> None:
    dates = pd.date_range("2025-01-01", periods=6)
    signals = pd.DataFrame([[3.0, 2.0, 1.0]] * 4, index=dates[:4], columns=["A", "B", "C"])
    opens = pd.DataFrame(100.0, index=dates, columns=signals.columns)
    closes = opens.copy()
    closes.loc[dates[1], "A"] = 110.0

    params = dict(nominal_open=opens, start="2025-01-01", end="2025-01-06",
                  initial_capital_yen=1_000, slippage_bps_per_side=0, repetitions=5, seed=42)
    first = MODULE.permutation_benchmark(signals, opens, closes, **params)
    second = MODULE.permutation_benchmark(signals, opens, closes, **params)

    assert first == second
    assert first["repetitions"] == 5
    assert 0 < first["one_sided_empirical_p"] <= 1


def test_permutation_benchmark_passes_selection_quantile() -> None:
    dates = pd.date_range("2025-01-01", periods=6)
    signals = pd.DataFrame(
        [[5.0, 4.0, 3.0, 2.0, 1.0]] * 4,
        index=dates[:4], columns=["A", "B", "C", "D", "E"],
    )
    prices = pd.DataFrame(100.0, index=dates, columns=signals.columns)
    result = MODULE.permutation_benchmark(
        signals, prices, prices, nominal_open=prices,
        start="2025-01-01", end="2025-01-06", initial_capital_yen=1_000,
        slippage_bps_per_side=0, repetitions=2, q=0.2,
    )
    assert result["repetitions"] == 2
