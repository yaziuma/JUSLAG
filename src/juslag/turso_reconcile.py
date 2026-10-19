"""Compare Git-owned daily reports with the latest Turso snapshots."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from juslag.turso_store import ensure_schema, load_snapshot, publish_snapshot, read_snapshot

FIRST_REPORT_DATE = "2026-07-09"


class ReconciliationError(ValueError):
    """Known failure with a fixed, credential-free diagnostic code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass
class ReconciliationProgress:
    stage: str = "connect"
    repair_started: bool = False
    schema_state: str = "not_attempted"
    snapshot_state: str = "not_attempted"
    audited_count: int = 0
    planned_count: int | None = None
    publish_attempt_count: int = 0
    publish_returned_count: int = 0
    insert_commit_ack_count: int = 0
    already_matching_count: int = 0
    push_returned_count: int = 0
    verified_count: int = 0
    current_report_date: str | None = None


def plan_reconciliation(
    conn: Any, reports_dir: Path, history_path: Path, *, since: str = FIRST_REPORT_DATE,
    progress: ReconciliationProgress | None = None,
) -> list[dict[str, Any]]:
    if progress is not None:
        progress.stage = "audit_input_validation"
    if not reports_dir.is_dir():
        raise ReconciliationError("reports_missing", "reports directory is missing")
    if len(since) != 10 or since[4] != "-" or since[7] != "-":
        raise ReconciliationError("invalid_since", "since must be YYYY-MM-DD")
    from datetime import date

    try:
        date.fromisoformat(since)
    except ValueError:
        raise ReconciliationError("invalid_since", "since must be YYYY-MM-DD") from None
    if progress is not None:
        progress.stage = "audit_schema_read"
    table_exists = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type = ? AND name = ?",
        ("table", "juslag_daily_snapshots"),
    ).fetchone()[0]
    repairs = []
    for path in sorted(reports_dir.glob("????-??-??.json")):
        if path.stem < since:
            continue
        if progress is not None:
            progress.stage = "audit_filename_validation"
            progress.current_report_date = None
        try:
            date.fromisoformat(path.stem)
        except ValueError:
            raise ReconciliationError("report_filename_invalid", "invalid report filename date") from None
        if progress is not None:
            progress.current_report_date = path.stem
            progress.stage = "audit_input_load"
        snapshot = load_snapshot(path, history_path)
        if snapshot["report_date"] != path.stem:
            raise ReconciliationError("report_date_mismatch", "report date differs from filename")
        if progress is not None:
            progress.stage = "audit_snapshot_read"
        current = read_snapshot(conn, report_date=path.stem) if table_exists else None
        if current is None or current["content_hash"] != snapshot["content_hash"]:
            predecessor = current["run_id"] if current else "missing"
            fingerprint = hashlib.sha256(predecessor.encode()).hexdigest()[:12]
            repairs.append({
                "snapshot": snapshot,
                "reason": "missing" if current is None else "different",
                "run_id": f"reconcile:{path.stem}:{snapshot['content_hash'][:16]}:{fingerprint}",
            })
        if progress is not None:
            progress.audited_count += 1
    if progress is not None:
        progress.stage = "audit_complete"
        progress.current_report_date = None
        progress.planned_count = len(repairs)
    return repairs


def repair_snapshots(
    conn: Any, repairs: list[dict[str, Any]], *, source_commit: str, published_at_utc: str,
    progress: ReconciliationProgress | None = None,
) -> None:
    if not repairs:
        return
    if progress is not None:
        progress.repair_started = True
        progress.current_report_date = None
        progress.stage = "repair_schema"
        progress.schema_state = "change_unconfirmed"
    ensure_schema(conn)
    if progress is not None:
        progress.stage = "repair_schema_push"
        progress.schema_state = "schema_call_returned"
    conn.push()
    if progress is not None:
        progress.schema_state = "push_call_returned"
    for item in repairs:
        if progress is not None:
            progress.stage = "repair_publish"
            progress.current_report_date = item["snapshot"]["report_date"]
            progress.publish_attempt_count += 1
            progress.snapshot_state = "commit_unconfirmed"
        inserted = publish_snapshot(
            conn, item["snapshot"], run_id=item["run_id"],
            source_commit=source_commit, published_at_utc=published_at_utc,
        )
        if progress is not None:
            progress.publish_returned_count += 1
            if inserted:
                progress.insert_commit_ack_count += 1
            else:
                progress.already_matching_count += 1
            progress.stage = "repair_push"
            progress.snapshot_state = "publish_returned_push_unconfirmed"
        # A previous push may have failed after the local commit; always retry it.
        conn.push()
        if progress is not None:
            progress.push_returned_count += 1
            progress.snapshot_state = "push_returned_unverified"


def verify_repairs(
    conn: Any, repairs: list[dict[str, Any]], *, progress: ReconciliationProgress | None = None,
) -> None:
    for item in repairs:
        snapshot = item["snapshot"]
        if progress is not None:
            progress.stage = "verify_read"
            progress.current_report_date = snapshot["report_date"]
        stored = read_snapshot(conn, report_date=snapshot["report_date"])
        if stored is None or stored["content_hash"] != snapshot["content_hash"]:
            code = "readback_missing" if stored is None else "readback_content_mismatch"
            raise ReconciliationError(code, "Cloud readback mismatch")
        if progress is not None:
            progress.verified_count += 1
    if progress is not None:
        progress.stage = "verified"
        progress.snapshot_state = "verified"
