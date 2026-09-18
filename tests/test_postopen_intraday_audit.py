from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/reports/audit_postopen_intraday.py"
SPEC = spec_from_file_location("audit_postopen_intraday", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_postopen_audit_counts_sparse_bars() -> None:
    bars = pd.DataFrame([
        {"ticker": "A", "bar_start_utc": "2025-01-06T00:00:00+00:00", "open": 100.0},
        {"ticker": "A", "bar_start_utc": "2025-01-06T00:15:00+00:00", "open": 101.0},
        {"ticker": "B", "bar_start_utc": "2025-01-06T00:15:00+00:00", "open": 100.0},
    ])

    detail, summary = MODULE.analyze_bars(bars)

    assert summary["ticker_days"] == 2
    assert summary["observed_proxy"] == 1
    assert summary["missing_open_or_postopen"] == 1
    assert summary["median_abs_drift_bps"] == 100.0
    assert detail.loc[detail["ticker"] == "A", "entry_bar_jst"].iloc[0].startswith("2025-01-06T09:15")
