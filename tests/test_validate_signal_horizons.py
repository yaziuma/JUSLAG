from __future__ import annotations

import runpy
from pathlib import Path

import pandas as pd

measure_horizons = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/reports/validate_signal_horizons.py")
)["measure_horizons"]


def test_horizons_use_next_jp_open_and_flag_discontinuous_prices() -> None:
    dates = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])
    tickers = ["A", "B", "C"]
    signals = pd.DataFrame([[3.0, 2.0, 1.0]], index=dates[:1], columns=tickers)
    opens = pd.DataFrame([[100, 100, 100], [100, 100, 100], [100, 100, 100]], index=dates, columns=tickers)
    closes = pd.DataFrame([[1000, 100, 100], [101, 100, 99], [200, 100, 99]], index=dates, columns=tickers)

    result = measure_horizons(signals, opens, closes, start="2026-01-05", end="2026-01-05")

    assert result["1"]["n"] == 1
    assert result["1"]["first_entry"] == "2026-01-06"
    assert result["1"]["gross_mean_bps"] == 200.0
    assert result["1"]["net_mean_bps"] == 180.0
    assert result["2"]["n"] == 0
