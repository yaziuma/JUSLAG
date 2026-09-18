from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/reports/audit_daily_report_timing.py"
SPEC = spec_from_file_location("audit_daily_report_timing", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_preopen_tradeable_gap_is_identified() -> None:
    market_open = pd.Timestamp("2026-09-18T09:00:00+09:00")
    report = {
        "date": "2026-09-18",
        "generated_at_utc": "2026-09-17T23:50:00+00:00",
        "history_entry": {
            "exec_jp_date": "2026-09-18",
            "tradeable": True,
            "selected_strategy": "gap_ovht_oc",
            "strategy_context": {"open_gap": 0.01},
        },
    }

    row = MODULE.audit_report(report, {"2026-09-18": market_open})

    assert row["timing"] == "before_open"
    assert row["open_gap_recorded"] is True


def test_target_price_rows_detects_absent_execution_day(tmp_path: Path) -> None:
    raw = tmp_path / "prices_tail_raw.csv"
    raw.write_text("ticker,date,open,close\n1625.T,2026-09-17,100,101\n", encoding="utf-8")

    assert MODULE.target_price_rows(raw, "2026-09-18") == 0
    assert MODULE.target_price_rows(raw, "2026-09-17") == 1
