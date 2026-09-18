import json
import sqlite3

import pytest

from juslag.turso_reconcile import plan_reconciliation
from juslag.turso_store import ensure_schema, publish_snapshot


def _files(tmp_path, date="2026-09-18", summary="first"):
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    (reports / f"{date}.json").write_text(json.dumps({"date": date}), encoding="utf-8")
    history = tmp_path / "history.jsonl"
    history.write_text(json.dumps({
        "jst_date": date, "report": f"data/reports/{date}.json",
        "summary": summary, "llm_status": "ok",
    }), encoding="utf-8")
    return reports, history


def test_missing_then_repaired_is_clean(tmp_path):
    reports, history = _files(tmp_path)
    conn = sqlite3.connect(":memory:")
    missing = plan_reconciliation(conn, reports, history)
    assert len(missing) == 1
    assert missing[0]["reason"] == "missing"
    assert missing[0]["run_id"] == plan_reconciliation(conn, reports, history)[0]["run_id"]
    ensure_schema(conn)
    assert publish_snapshot(
        conn, missing[0]["snapshot"], run_id=missing[0]["run_id"],
        source_commit="abc", published_at_utc="2026-09-18T01:00:00Z",
    )
    assert plan_reconciliation(conn, reports, history) == []


def test_changed_git_summary_creates_new_run(tmp_path):
    reports, history = _files(tmp_path)
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    first = plan_reconciliation(conn, reports, history)[0]
    publish_snapshot(
        conn, first["snapshot"], run_id=first["run_id"],
        source_commit="abc", published_at_utc="2026-09-18T01:00:00Z",
    )
    _files(tmp_path, summary="corrected")
    changed = plan_reconciliation(conn, reports, history)[0]
    assert changed["reason"] == "different"
    assert changed["run_id"] != first["run_id"]
    publish_snapshot(
        conn, changed["snapshot"], run_id=changed["run_id"],
        source_commit="def", published_at_utc="2026-09-18T02:00:00Z",
    )
    assert plan_reconciliation(conn, reports, history) == []
    assert conn.execute("SELECT count(*) FROM juslag_daily_snapshots").fetchone()[0] == 2


def test_rollout_boundary_and_filename_validation(tmp_path):
    reports, history = _files(tmp_path, date="2026-09-17")
    conn = sqlite3.connect(":memory:")
    assert plan_reconciliation(conn, reports, history) == []
    with pytest.raises(ValueError):
        plan_reconciliation(conn, reports, history, since="2026-99-99")
    _files(tmp_path)
    (reports / "2026-09-18.json").write_text('{"date":"2026-09-17"}', encoding="utf-8")
    history.write_text(json.dumps({
        "jst_date": "2026-09-17", "report": "data/reports/2026-09-17.json",
        "summary": "old", "llm_status": "ok",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="report date differs"):
        plan_reconciliation(conn, reports, history)
