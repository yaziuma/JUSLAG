import runpy
from pathlib import Path

import pandas as pd

compare_return_order = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/reports/analyze_return_alignment.py")
)["compare_return_order"]


def test_market_first_excludes_intervening_us_session() -> None:
    dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"])
    close = pd.DataFrame({"US": [100.0, 110.0, 121.0], "JP": [200.0, None, 220.0]}, index=dates)

    result = compare_return_order(close, ["US"], ["JP"])

    assert result["common_days"] == 2
    assert result["us_only_days"] == 1
    assert result["different_days"] == 1
    assert result["different_cells"] == 1
    assert result["by_market"]["us"]["mean_abs_bps_on_different_cells"] == 1100.0
    assert result["by_market"]["jp"]["different_cells"] == 0
