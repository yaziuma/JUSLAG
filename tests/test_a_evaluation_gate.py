from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd
import yaml


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/reports/check_a_evaluation_gate.py"
SPEC = spec_from_file_location("check_a_evaluation_gate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
GATE = yaml.safe_load((Path(__file__).resolve().parents[1] / "config/a_evaluation_gate.yaml").read_text())


def test_proxy_gate_counts_only_timely_covered_sessions() -> None:
    rows = []
    for ticker in [f"T{i}" for i in range(17)]:
        rows.append({"ticker": ticker, "bar_start_utc": "2026-09-24T00:10:00+00:00",
                     "observed_at_utc": "2026-09-24T00:16:00+00:00", "open": 100})
    rows.append({"ticker": "T0", "bar_start_utc": "2026-09-25T00:10:00+00:00",
                 "observed_at_utc": "2026-09-25T01:00:00+00:00", "open": 100})

    result = MODULE.evaluate_proxy(pd.DataFrame(rows), GATE)

    assert result["observed_sessions"] == 2
    assert result["complete_sessions"] == 1
    assert result["ready"] is False


def test_holdout_calendar_is_frozen_to_120_sessions() -> None:
    before = MODULE.evaluate_holdout(GATE, "2026-09-23")
    final = MODULE.evaluate_holdout(GATE, "2027-03-23")
    assert before["calendar_sessions"] == 120
    assert before["completed_sessions"] == 0
    assert final["completed_sessions"] == 120
    assert final["ready"] is True


def test_sbi_public_conditions_cannot_satisfy_broker_evidence() -> None:
    result = MODULE.audit_snapshots(Path("does-not-exist"), "2026-09-24")
    assert result["observed_sessions"] == 0
    assert result["availability_known_from_public_source"] is False
    assert result["broker_execution_records_present"] is False
    assert result["informational_only"] is True
