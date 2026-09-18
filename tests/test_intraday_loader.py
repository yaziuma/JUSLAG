from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from juslag.intraday import load_intraday_bars


def test_snapshot_loader_uses_first_observed_version(tmp_path: Path) -> None:
    rows = pd.DataFrame([
        {"ticker": "1625.T", "bar_start_utc": "2026-09-18T00:10:00+00:00",
         "observed_at_utc": "2026-09-18T00:40:00+00:00", "open": 102.0},
        {"ticker": "1625.T", "bar_start_utc": "2026-09-18T00:10:00+00:00",
         "observed_at_utc": "2026-09-18T00:16:00+00:00", "open": 100.0},
    ])
    rows.to_csv(tmp_path / "2026-09-18.csv", index=False)

    loaded = load_intraday_bars(snapshot_dir=tmp_path)

    assert len(loaded) == 1
    assert loaded.iloc[0]["open"] == 100.0
    assert loaded.iloc[0]["observed_at_utc"] == "2026-09-18T00:16:00+00:00"


def test_local_sqlite_loader_matches_capture(tmp_path: Path) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    script = Path(__file__).resolve().parents[1] / "scripts/ops/capture_intraday.py"
    spec = spec_from_file_location("capture_intraday_for_loader", script)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    index = pd.DatetimeIndex(["2026-09-18 09:10:00+09:00"])
    cols = pd.MultiIndex.from_product([["1625.T"], ["Open", "High", "Low", "Close", "Volume"]])
    bars = pd.DataFrame([[100, 101, 99, 100, 1000]], index=index, columns=cols)
    db = tmp_path / "bars.sqlite"
    module.store_capture(db, bars, datetime(2026, 9, 18, 0, 16, tzinfo=timezone.utc))

    loaded = load_intraday_bars(db=db)

    assert len(loaded) == 1
    assert loaded.iloc[0]["open"] == 100.0
