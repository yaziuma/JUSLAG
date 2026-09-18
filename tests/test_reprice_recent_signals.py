from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/reports/reprice_recent_signals.py"
SPEC = spec_from_file_location("reprice_recent_signals", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_repricing_requires_all_selected_postopen_bars() -> None:
    dates = pd.DatetimeIndex(["2025-01-01", "2025-01-02"])
    signals = pd.DataFrame([[3.0, 2.0, 1.0]], index=dates[:1], columns=["A", "B", "C"])
    opening = pd.DataFrame(100.0, index=dates, columns=signals.columns)
    close = opening.copy()
    close.loc[dates[1], "A"] = 110.0
    close.loc[dates[1], "C"] = 90.0
    bars = pd.DataFrame([
        {"ticker": "A", "bar_start_utc": "2025-01-02T00:10:00+00:00", "open": 105.0},
        {"ticker": "C", "bar_start_utc": "2025-01-02T00:10:00+00:00", "open": 95.0},
    ])

    positions, days = MODULE.reprice_signals(signals, opening, close, bars)
    assert len(positions) == 2
    assert days[0]["complete"] is True
    assert round(days[0]["same_open_gross_bps"]) == 2000
    assert days[0]["postopen_proxy_gross_bps"] < days[0]["same_open_gross_bps"]

    positions, days = MODULE.reprice_signals(signals, opening, close, bars.iloc[:1])
    assert days[0]["complete"] is False
    assert days[0]["postopen_proxy_gross_bps"] == ""
    assert any(row["status"] == "missing_postopen_bar" for row in positions)
