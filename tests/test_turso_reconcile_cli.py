"""Inert database fakes only: no real DB, credentials, broker or network."""
from __future__ import annotations

import json
import socket
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from juslag import turso_reconcile as core
from juslag.turso_store import load_snapshot

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/ops"))
SPEC = spec_from_file_location("reconcile_cli_candidate", ROOT / "scripts/ops/turso_reconcile.py")
assert SPEC is not None and SPEC.loader is not None
cli = module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


@pytest.fixture(autouse=True)
def forbid_real_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("real DB/network connections are forbidden")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    sdk = ModuleType("libsql")
    setattr(sdk, "connect", forbidden)
    monkeypatch.setitem(sys.modules, "libsql", sdk)


class Cursor:
    def fetchone(self):
        return (1,)


class FakeConnection:
    def __init__(self, state, role):
        self.state = state
        self.role = role
        self.closed = False

    def execute(self, sql, params):
        assert sql.lstrip().startswith("SELECT")
        self.state.selects.append(sql)
        if self.state.audit_schema_error:
            raise self.state.audit_schema_error
        return Cursor()

    def push(self):
        self.state.push_calls += 1
        if self.state.push_calls == self.state.fail_push_at:
            raise ValueError("SDK transport failure SYNTHETIC_SECRET")

    def close(self):
        self.closed = True


class State:
    def __init__(self):
        self.rows: dict[str, dict[str, Any]] = {}
        self.selects: list[str] = []
        self.connections: list[FakeConnection] = []
        self.publish_calls = 0
        self.push_calls = 0
        self.schema_calls = 0
        self.schema_changed = False
        self.audit_schema_error: Exception | None = None
        self.audit_read_error: Exception | None = None
        self.connect_error: Exception | None = None
        self.verifier_connect_error: Exception | None = None
        self.fail_before_publish_at = -1
        self.fail_after_commit_at = -1
        self.conflict_at = -1
        self.fail_push_at = -1
        self.fail_schema = False
        self.verify_missing_date: str | None = None
        self.verify_mismatch_date: str | None = None
        self.verify_read_error: Exception | None = None

    def connect(self, path):
        role = "verify" if Path(path).stem == "verify" else "audit"
        if self.connect_error:
            raise self.connect_error
        if role == "verify" and self.verifier_connect_error:
            raise self.verifier_connect_error
        conn = FakeConnection(self, role)
        self.connections.append(conn)
        return conn

    def ensure_schema(self, conn):
        self.schema_calls += 1
        self.schema_changed = True
        if self.fail_schema:
            raise ValueError("schema response lost SYNTHETIC_SECRET")

    def publish(self, conn, snapshot, *, run_id, source_commit, published_at_utc):
        self.publish_calls += 1
        if self.publish_calls == self.fail_before_publish_at:
            raise ValueError("before write SYNTHETIC_SECRET")
        if self.publish_calls == self.conflict_at:
            self.rows[run_id] = {**snapshot, "run_id": run_id, "content_hash": "concurrent-different"}
        existing = self.rows.get(run_id)
        if existing:
            if existing["content_hash"] != snapshot["content_hash"]:
                raise ValueError("run_id already exists with different content")
            return False
        self.rows[run_id] = {**snapshot, "run_id": run_id}
        if self.publish_calls == self.fail_after_commit_at:
            raise ValueError("commit response lost SYNTHETIC_SECRET")
        return True

    def read(self, conn, *, report_date):
        if conn.role == "audit" and self.audit_read_error:
            raise self.audit_read_error
        if conn.role == "verify":
            if self.verify_read_error:
                raise self.verify_read_error
            if report_date == self.verify_missing_date:
                return None
            if report_date == self.verify_mismatch_date:
                return {"content_hash": "different"}
        values = [row for row in self.rows.values() if row["report_date"] == report_date]
        return values[-1] if values else None


@pytest.fixture
def context(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    history = tmp_path / "history.jsonl"
    entries = []
    for day in ("2026-10-16", "2026-10-19"):
        (reports / f"{day}.json").write_text(json.dumps({"date": day}))
        entries.append({"jst_date": day, "report": f"data/reports/{day}.json",
                        "summary": "synthetic summary", "llm_status": "ok"})
    history.write_text("\n".join(json.dumps(row) for row in entries) + "\n")
    state = State()
    monkeypatch.setattr(cli, "connect", state.connect)
    monkeypatch.setattr(core, "ensure_schema", state.ensure_schema)
    monkeypatch.setattr(core, "publish_snapshot", state.publish)
    monkeypatch.setattr(core, "read_snapshot", state.read)
    monkeypatch.setenv("JUSLAG_WRITE_TURSO", "1")
    monkeypatch.setenv("GITHUB_SHA", "offline-synthetic-commit")
    return SimpleNamespace(state=state, reports=reports, history=history, monkeypatch=monkeypatch)


def run(context, *, repair=True, limit=10):
    args = ["reconcile", "--reports", str(context.reports), "--history", str(context.history),
            "--max-repairs", str(limit)]
    if repair:
        args.append("--repair")
    context.monkeypatch.setattr(sys, "argv", args)
    cli.main()


def failure(context, **kwargs):
    with pytest.raises(SystemExit) as exc:
        run(context, **kwargs)
    message = str(exc.value)
    assert "SYNTHETIC_SECRET" not in message
    return json.loads(message.split("failed: ", 1)[1])


def final_status(capsys):
    output = capsys.readouterr().out
    rows = [json.loads(line.split(": ", 1)[1]) for line in output.splitlines()
            if line.startswith("RECONCILE_STATUS: ")]
    assert "SYNTHETIC_SECRET" not in output
    return rows[-1], output


def test_connect_failure_is_before_repair_and_redacted(context):
    context.state.connect_error = ValueError("credential URL SYNTHETIC_SECRET")
    result = failure(context)
    assert result["stage"] == "connect"
    assert not result["repair_started"] and result["publish_attempt_count"] == 0
    assert not context.state.rows and not context.state.schema_changed


def test_schema_read_401_is_audit_failure_not_repair(context):
    context.state.audit_schema_error = ValueError("HTTP 401 Unauthorized SYNTHETIC_SECRET")
    result = failure(context)
    assert result["stage"] == "audit_schema_read" and result["code"] == "remote_auth_rejected"
    assert result["snapshot_state"] == "not_attempted" and not result["repair_started"]
    assert context.state.schema_calls == 0 and context.state.publish_calls == 0
    assert all(conn.closed for conn in context.state.connections)


def test_missing_summary_is_input_load_failure(context):
    context.history.write_text("")
    result = failure(context)
    assert result["stage"] == "audit_input_load" and result["code"] == "summary_missing"
    assert result["current_report_date"] == "2026-10-16"
    assert not result["repair_started"] and not context.state.rows


def test_stored_hash_failure_during_audit_does_not_write(context):
    context.state.audit_read_error = ValueError("snapshot hash mismatch")
    result = failure(context)
    assert result["stage"] == "audit_snapshot_read" and result["code"] == "stored_hash_mismatch"
    assert not result["repair_started"] and context.state.schema_calls == 0


def test_audit_only_differences_never_repair(context, capsys):
    with pytest.raises(SystemExit) as exc:
        run(context, repair=False)
    assert exc.value.code == 2
    status, _ = final_status(capsys)
    assert status["code"] == "differences_found_read_only" and status["planned_count"] == 2
    assert not status["repair_requested"] and not status["repair_started"]
    assert context.state.schema_calls == context.state.publish_calls == context.state.push_calls == 0
    assert not context.state.rows


def test_repair_limit_failure_is_before_any_mutation(context):
    result = failure(context, limit=1)
    assert result["stage"] == "repair_limit_check" and result["code"] == "repair_limit_exceeded"
    assert not result["repair_started"] and context.state.schema_calls == 0


def test_metadata_failure_is_before_repair(context):
    context.monkeypatch.delenv("GITHUB_SHA")
    def failed_metadata(*args, **kwargs):
        raise ValueError("metadata failure SYNTHETIC_SECRET")
    context.monkeypatch.setattr(cli.subprocess, "check_output", failed_metadata)
    result = failure(context)
    assert result["stage"] == "repair_metadata" and not result["repair_started"]
    assert context.state.schema_calls == 0


def test_success_counts_are_acknowledgements_until_verified(context, capsys):
    run(context)
    result, output = final_status(capsys)
    assert result["stage"] == "verified" and result["snapshot_state"] == "verified"
    assert result["insert_commit_ack_count"] == result["verified_count"] == 2
    assert result["publish_attempt_count"] == result["push_returned_count"] == 2
    assert "PASS: reconciled 2" in output and len(context.state.rows) == 2
    assert all(conn.closed for conn in context.state.connections)


def test_partial_failure_preserves_first_ack_and_does_not_retry(context):
    context.state.fail_before_publish_at = 2
    result = failure(context)
    assert result["stage"] == "repair_publish" and result["repair_started"]
    assert result["publish_attempt_count"] == 2 and result["insert_commit_ack_count"] == 1
    assert result["snapshot_state"] == "commit_unconfirmed" and result["verified_count"] == 0
    assert len(context.state.rows) == 1 and context.state.publish_calls == 2


def test_lost_commit_response_does_not_claim_no_write(context):
    context.state.fail_after_commit_at = 1
    result = failure(context)
    assert len(context.state.rows) == 1  # inert fake has changed; acknowledgement was lost
    assert result["snapshot_state"] == "commit_unconfirmed"
    assert result["insert_commit_ack_count"] == 0 and result["publish_returned_count"] == 0
    assert context.state.publish_calls == 1


def test_push_failure_after_commit_is_unverified(context):
    context.state.fail_push_at = 2
    result = failure(context)
    assert result["stage"] == "repair_push" and result["insert_commit_ack_count"] == 1
    assert result["snapshot_state"] == "publish_returned_push_unconfirmed"
    assert result["push_returned_count"] == 0 and len(context.state.rows) == 1


def test_verifier_connect_failure_keeps_commit_counts(context):
    context.state.verifier_connect_error = ValueError("HTTP 403 Forbidden SYNTHETIC_SECRET")
    result = failure(context)
    assert result["stage"] == "verify_connect" and result["code"] == "remote_access_forbidden"
    assert result["insert_commit_ack_count"] == 2 and result["verified_count"] == 0
    assert result["snapshot_state"] == "push_returned_unverified"
    assert context.state.connections[0].closed


def test_partial_readback_failure_does_not_report_batch_success(context, capsys):
    context.state.verify_mismatch_date = "2026-10-19"
    result = failure(context)
    assert result["stage"] == "verify_read" and result["code"] == "readback_content_mismatch"
    assert result["verified_count"] == 1 and result["insert_commit_ack_count"] == 2
    assert result["current_report_date"] == "2026-10-19"
    assert "PASS: reconciled" not in capsys.readouterr().out


def test_missing_readback_is_distinct_from_mismatch(context):
    context.state.verify_missing_date = "2026-10-16"
    result = failure(context)
    assert result["code"] == "readback_missing" and result["verified_count"] == 0
    assert result["insert_commit_ack_count"] == 2


def test_corrupt_hash_on_readback_is_not_retry_or_success(context):
    context.state.verify_read_error = ValueError("snapshot hash mismatch")
    result = failure(context)
    assert result["stage"] == "verify_read" and result["code"] == "stored_hash_mismatch"
    assert result["verified_count"] == 0 and context.state.publish_calls == 2


def test_schema_failure_does_not_claim_database_unmodified(context):
    context.state.fail_schema = True
    result = failure(context)
    assert result["stage"] == "repair_schema" and result["schema_state"] == "change_unconfirmed"
    assert result["repair_started"] and result["snapshot_state"] == "not_attempted"
    assert context.state.schema_changed and result["publish_attempt_count"] == 0


def test_matching_data_finishes_audit_without_writes(context, capsys):
    for path in context.reports.glob("*.json"):
        snap = load_snapshot(path, context.history)
        context.state.rows[path.stem] = {**snap, "run_id": path.stem}
    run(context, repair=False)
    result, _ = final_status(capsys)
    assert result["planned_count"] == 0 and not result["repair_started"]
    assert context.state.schema_calls == context.state.publish_calls == 0


def test_optional_progress_preserves_run_ids_and_existing_push_retry(context):
    conn = context.state.connect(Path("audit.db"))
    plan = core.plan_reconciliation(conn, context.reports, context.history)
    progress = core.ReconciliationProgress()
    assert plan == core.plan_reconciliation(conn, context.reports, context.history, progress=progress)
    context.state.fail_push_at = 2
    with pytest.raises(ValueError):
        core.repair_snapshots(conn, plan, source_commit="offline", published_at_utc="2026-10-19T00:00Z")
    assert len(context.state.rows) == 1
    core.repair_snapshots(conn, plan, source_commit="offline", published_at_utc="2026-10-19T00:00Z")
    assert len(context.state.rows) == 2  # same immutable IDs, no duplicate replacement
    assert context.state.push_calls == 5
    core.verify_repairs(conn, plan)


def test_repair_still_requires_existing_write_gate(context):
    context.monkeypatch.delenv("JUSLAG_WRITE_TURSO")
    with pytest.raises(SystemExit, match="writes disabled"):
        run(context)
    assert not context.state.connections and not context.state.rows


def test_progress_and_audit_markers_are_flushed_before_repair(context, monkeypatch, capsys):
    import builtins
    calls: list[dict] = []
    def tracked_print(*args, **kwargs):
        calls.append(kwargs)
        builtins.print(*args, **kwargs)
    monkeypatch.setattr(cli, "print", tracked_print, raising=False)
    with pytest.raises(SystemExit) as exc:
        run(context, repair=False)
    assert exc.value.code == 2
    assert calls and all(call.get("flush") is True for call in calls)
    assert "Audit: 2" in capsys.readouterr().out


def test_current_conflict_does_not_hide_previous_commits(context):
    context.state.conflict_at = 2
    result = failure(context)
    assert result["code"] == "run_id_content_conflict"
    assert result["snapshot_state"] == "current_publish_not_written"
    assert result["insert_commit_ack_count"] == 1 and result["publish_attempt_count"] == 2
    assert result["verified_count"] == 0
    assert any(row["content_hash"] == "concurrent-different" for row in context.state.rows.values())


def test_invalid_filename_after_valid_dates_is_still_before_repair(context):
    (context.reports / "2026-99-99.json").write_text('{"date":"2026-99-99"}')
    result = failure(context)
    assert result["stage"] == "audit_filename_validation"
    assert result["code"] == "report_filename_invalid" and result["current_report_date"] is None
    assert result["audited_count"] == 2 and result["planned_count"] is None
    assert not result["repair_started"] and context.state.publish_calls == 0
