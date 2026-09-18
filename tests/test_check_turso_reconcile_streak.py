from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ops/check_turso_reconcile_streak.py"
SPEC = importlib.util.spec_from_file_location("check_turso_reconcile_streak", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_scheduled_runs_ignore_manual_and_sort_newest_first():
    runs = [
        {"event": "schedule", "createdAt": "2026-09-19T00:30:00Z"},
        {"event": "workflow_dispatch", "createdAt": "2026-09-20T00:30:00Z"},
        {"event": "schedule", "createdAt": "2026-09-21T00:30:00Z"},
    ]
    assert [run["createdAt"] for run in module.scheduled_runs(runs)] == [
        "2026-09-21T00:30:00Z", "2026-09-19T00:30:00Z",
    ]


def test_run_passes_requires_success_and_clean_audit():
    run = {"status": "completed", "conclusion": "success"}
    assert module.run_passes(run, module.AUDIT_OK)
    assert not module.run_passes(run, "Audit: 1 date(s) require repair since 2026-09-18")
    assert not module.run_passes({**run, "conclusion": "skipped"}, module.AUDIT_OK)
