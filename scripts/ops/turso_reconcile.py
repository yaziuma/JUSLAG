"""Audit or repair Turso daily snapshots against Git-owned reports."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from contextlib import suppress
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from juslag.turso_reconcile import (
    FIRST_REPORT_DATE, ReconciliationError, ReconciliationProgress,
    plan_reconciliation, repair_snapshots, verify_repairs,
)
from turso_daily import connect


_SNAPSHOT_CODES = {
    "report_date_missing", "summary_missing", "summary_path_mismatch",
    "summary_text_missing", "llm_status_invalid", "snapshot_secret_detected",
    "snapshot_webhook_detected", "noncanonical_json", "publish_metadata_missing",
    "run_id_content_conflict", "stored_hash_mismatch", "unsupported_url_scheme",
}
_MESSAGES = {
    "report date is missing": "report_date_missing",
    "matching summary is missing": "summary_missing",
    "summary report path differs": "summary_path_mismatch",
    "summary text is missing": "summary_text_missing",
    "invalid llm status": "llm_status_invalid",
    "snapshot contains a configured secret": "snapshot_secret_detected",
    "snapshot contains a Slack webhook": "snapshot_webhook_detected",
    "run_id already exists with different content": "run_id_content_conflict",
    "snapshot hash mismatch": "stored_hash_mismatch",
    "unsupported Turso URL scheme": "unsupported_url_scheme",
}


def failure_code(exc: Exception) -> str:
    if isinstance(exc, ReconciliationError):
        return exc.code
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code in _SNAPSHOT_CODES:
        return code
    # Never print/save SDK text: it may contain credentials or URLs.
    message = str(exc)
    if isinstance(exc, ValueError):
        if message in _MESSAGES:
            return _MESSAGES[message]
        if re.search(r"\b401\b", message) and re.search(r"unauthoriz|unauthenticat|authorization", message, re.I):
            return "remote_auth_rejected"
        if re.search(r"\b403\b", message) and re.search(r"forbidden|permission|authoriz", message, re.I):
            return "remote_access_forbidden"
    return "unclassified"


def diagnostic(progress: ReconciliationProgress, *, repair_requested: bool, code: str) -> dict:
    return {"schema_version": 1, "repair_requested": repair_requested, "code": code, **asdict(progress)}


def emit(progress: ReconciliationProgress, *, repair_requested: bool, code: str) -> None:
    print("RECONCILE_STATUS: " + json.dumps(
        diagnostic(progress, repair_requested=repair_requested, code=code), sort_keys=True,
    ), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=FIRST_REPORT_DATE)
    parser.add_argument("--reports", type=Path, default=Path("data/reports"))
    parser.add_argument("--history", type=Path, default=Path("data/history.jsonl"))
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--max-repairs", type=int, default=10)
    args = parser.parse_args()
    if args.max_repairs < 1:
        parser.error("--max-repairs must be positive")
    if args.repair and os.getenv("JUSLAG_WRITE_TURSO", "").lower() not in {"1", "true"}:
        raise SystemExit("Turso writes disabled; set JUSLAG_WRITE_TURSO=1")
    progress = ReconciliationProgress()
    connections = []
    try:
        emit(progress, repair_requested=args.repair, code="started")
        with tempfile.TemporaryDirectory(prefix="juslag-turso-reconcile-") as root:
            root_path = Path(root)
            conn = connect(root_path / "audit.db")
            connections.append(conn)
            repairs = plan_reconciliation(
                conn, args.reports, args.history, since=args.since, progress=progress,
            )
            print(f"Audit: {len(repairs)} date(s) require repair since {args.since}", flush=True)
            emit(progress, repair_requested=args.repair, code="audit_complete")
            if not repairs:
                return
            for item in repairs:
                print(f"  {item['snapshot']['report_date']}: {item['reason']}", flush=True)
            if not args.repair:
                emit(progress, repair_requested=False, code="differences_found_read_only")
                raise SystemExit(2)
            progress.stage = "repair_limit_check"
            if len(repairs) > args.max_repairs:
                raise ReconciliationError("repair_limit_exceeded", "repair count exceeds --max-repairs")
            progress.stage = "repair_metadata"
            source_commit = os.getenv("GITHUB_SHA") or subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True,
            ).strip()
            progress.stage = "repair_start"
            emit(progress, repair_requested=True, code="repair_about_to_start")
            repair_snapshots(
                conn, repairs, source_commit=source_commit,
                published_at_utc=datetime.now(timezone.utc).isoformat(), progress=progress,
            )
            progress.stage = "verify_connect"
            progress.current_report_date = None
            emit(progress, repair_requested=True, code="repair_calls_returned_unverified")
            verifier = connect(root_path / "verify.db")
            connections.append(verifier)
            verify_repairs(verifier, repairs, progress=progress)
            emit(progress, repair_requested=True, code="verified")
            print(f"PASS: reconciled {len(repairs)} date(s)", flush=True)
    except Exception as exc:  # noqa: BLE001 - do not expose credential-bearing SDK messages
        code = failure_code(exc)
        if code == "run_id_content_conflict" and progress.stage == "repair_publish":
            progress.snapshot_state = "current_publish_not_written"
        detail = diagnostic(progress, repair_requested=args.repair, code=code)
        detail["exception_type"] = type(exc).__name__
        raise SystemExit("Turso reconciliation failed: " + json.dumps(detail, sort_keys=True)) from None
    finally:
        for connection in reversed(connections):
            with suppress(Exception):
                connection.close()


if __name__ == "__main__":
    main()
