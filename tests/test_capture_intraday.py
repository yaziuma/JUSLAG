from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sqlite3

import pandas as pd
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ops/capture_intraday.py"
SPEC = spec_from_file_location("capture_intraday", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_store_capture_preserves_observation_versions(tmp_path: Path) -> None:
    index = pd.DatetimeIndex(["2026-09-18 09:00:00+09:00"])
    columns = pd.MultiIndex.from_product([["1625.T"], ["Open", "High", "Low", "Close", "Volume"]])
    bars = pd.DataFrame([[100, 102, 99, 101, 1000]], index=index, columns=columns)
    db = tmp_path / "intraday.sqlite"
    first = datetime(2026, 9, 18, 1, 0, tzinfo=timezone.utc)
    second = datetime(2026, 9, 18, 2, 0, tzinfo=timezone.utc)

    assert MODULE.store_capture(db, bars, first) == {"1625.T": 1}
    bars.loc[:, ("1625.T", "Close")] = 103
    MODULE.store_capture(db, bars, second)
    MODULE.store_capture(db, bars, second)

    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT close, observed_at_utc FROM intraday_bars ORDER BY observed_at_utc").fetchall()
    assert rows == [(101.0, first.isoformat()), (103.0, second.isoformat())]


def test_store_capture_requires_aware_observation_time(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        MODULE.store_capture(tmp_path / "intraday.sqlite", pd.DataFrame(), datetime(2026, 9, 18))


def test_opening_snapshot_keeps_todays_versions_and_is_idempotent(tmp_path: Path) -> None:
    index = pd.DatetimeIndex([
        "2026-09-17 09:10:00+09:00", "2026-09-18 09:00:00+09:00",
        "2026-09-18 09:10:00+09:00", "2026-09-18 09:35:00+09:00",
    ])
    columns = pd.MultiIndex.from_product([["1625.T"], ["Open", "High", "Low", "Close", "Volume"]])
    bars = pd.DataFrame([[100, 101, 99, 100, 1000]] * 4, index=index, columns=columns)
    first = datetime(2026, 9, 18, 0, 16, tzinfo=timezone.utc)
    second = datetime(2026, 9, 18, 0, 40, tzinfo=timezone.utc)

    first_rows = MODULE.opening_snapshot_rows(bars, first)
    assert len(first_rows) == 2
    assert first_rows[0]["observed_at_utc"] == first.isoformat()
    path = MODULE.append_opening_snapshot(tmp_path, first_rows, first)
    MODULE.append_opening_snapshot(tmp_path, first_rows, first)
    later_rows = MODULE.opening_snapshot_rows(bars, second)
    MODULE.append_opening_snapshot(tmp_path, later_rows, second)
    saved = pd.read_csv(path)
    assert len(saved) == 4
    assert saved["observed_at_utc"].nunique() == 2


def test_opening_snapshot_ignores_non_session_day(tmp_path: Path) -> None:
    index = pd.DatetimeIndex(["2026-09-17 09:10:00+09:00"])
    columns = pd.MultiIndex.from_product([["1625.T"], ["Open", "High", "Low", "Close", "Volume"]])
    bars = pd.DataFrame([[100, 101, 99, 100, 1000]], index=index, columns=columns)
    observed = datetime(2026, 9, 18, 0, 40, tzinfo=timezone.utc)
    rows = MODULE.opening_snapshot_rows(bars, observed)
    assert rows == []
    assert MODULE.append_opening_snapshot(tmp_path, rows, observed) is None
