from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/reports/audit_information_time.py"
SPEC = spec_from_file_location("audit_information_time", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_audit_dates_handles_us_only_day_and_jp_holiday() -> None:
    us = pd.DatetimeIndex(["2025-01-09", "2025-01-10", "2025-01-13", "2025-01-14"])
    jp = pd.DatetimeIndex(["2025-01-09", "2025-01-10", "2025-01-14", "2025-01-15"])

    rows = MODULE.audit_dates(us, jp, pretrain_end="2024-12-31", window=2, start="2025-01-01")

    assert rows[0]["signal_date"] == "2025-01-13"
    assert rows[0]["signal_path"] == "us_only_not_historical_signal"
    assert rows[0]["last_jp_input_date"] == "2025-01-10"
    assert rows[0]["execution_jp_date"] == "2025-01-14"
    assert rows[0]["date_order"] == "ok"
    assert rows[-1]["execution_jp_date"] == "2025-01-15"
    assert all(row["gap_after_open_fill"] == "unverified_same_open_assumption" for row in rows)


def test_audit_dates_fails_without_next_jp_session() -> None:
    us = pd.DatetimeIndex(["2025-01-09", "2025-01-10", "2025-01-13"])
    jp = pd.DatetimeIndex(["2025-01-09", "2025-01-10"])

    rows = MODULE.audit_dates(us, jp, pretrain_end="2024-12-31", window=2, start="2025-01-01")

    assert rows[0]["execution_jp_date"] == ""
    assert rows[0]["date_order"] == "fail"
