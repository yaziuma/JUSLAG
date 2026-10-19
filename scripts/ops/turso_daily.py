"""Publish finalized JUSLAG operation data to Turso or read it back."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from juslag.turso_store import SnapshotError, ensure_schema, load_snapshot, publish_snapshot, read_snapshot


def connect(path: Path):
    import libsql

    url = os.environ["JUSLAG_TURSO_DATABASE_URL"]
    token = os.environ["JUSLAG_TURSO_AUTH_TOKEN"]
    if not url.startswith(("libsql://", "turso://")):
        raise SnapshotError("unsupported_url_scheme", "unsupported Turso URL scheme")
    return RemoteConnection(libsql.connect(database=url, auth_token=token))


class RemoteConnection:
    """DB-API connection with a no-op push for the existing publisher contract."""

    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def push(self):
        # libsql commits directly to Cloud; there is no local replica to push.
        pass


def failure_code(exc: Exception) -> str:
    if isinstance(exc, SnapshotError):
        return exc.code
    # The SDK wraps HTTP failures in ValueError. Inspect only for bounded
    # categories; never print/persist the potentially credential-bearing text.
    if isinstance(exc, ValueError):
        message = str(exc)
        if re.search(r"\b401\b", message) and re.search(r"unauthoriz|unauthenticat", message, re.I):
            return "remote_auth_rejected"
        if re.search(r"\b403\b", message) and re.search(r"forbidden|permission|authoriz", message, re.I):
            return "remote_access_forbidden"
    return "unclassified"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("--report", type=Path, required=True)
    publish.add_argument("--history", type=Path, default=Path("data/history.jsonl"))
    publish.add_argument("--run-id")
    check = commands.add_parser("check", help="validate local inputs without any Cloud connection")
    check.add_argument("--report", type=Path, required=True)
    check.add_argument("--history", type=Path, default=Path("data/history.jsonl"))
    read = commands.add_parser("read")
    selection = read.add_mutually_exclusive_group()
    selection.add_argument("--date")
    selection.add_argument("--run-id")
    read.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "publish" and os.getenv("JUSLAG_WRITE_TURSO", "").lower() not in {"1", "true"}:
        raise SystemExit("Turso writes disabled; set JUSLAG_WRITE_TURSO=1")

    stage = "input_validation" if args.command in {"publish", "check"} else "reader_connect"
    schema_state = "not_attempted"
    snapshot_state = "not_attempted"
    connections = []
    try:
        # Invalid files must not connect to Cloud or create/modify its schema.
        if args.command in {"publish", "check"}:
            snapshot = load_snapshot(args.report, args.history)
            if args.command == "check":
                print(f"PASS: local input date={snapshot['report_date']} content_hash={snapshot['content_hash']}")
                return
            stage = "publish_metadata"
            source_commit = os.getenv("GITHUB_SHA") or subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True,
            ).strip()
            run_id = args.run_id or (
                f"actions:{os.environ['GITHUB_RUN_ID']}:{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
                if os.getenv("GITHUB_RUN_ID") else f"local:{uuid.uuid4().hex}"
            )
        with tempfile.TemporaryDirectory(prefix="juslag-turso-daily-") as root:
            path = Path(root)
            stage = "writer_connect" if args.command == "publish" else "reader_connect"
            conn = connect(path / "writer.db")
            connections.append(conn)
            if args.command == "publish":
                stage = "schema"
                schema_state = "change_unconfirmed"
                ensure_schema(conn)
                conn.push()
                schema_state = "ready"
                stage = "publish"
                snapshot_state = "commit_unconfirmed"
                inserted = publish_snapshot(
                    conn, snapshot, run_id=run_id, source_commit=source_commit,
                    published_at_utc=datetime.now(timezone.utc).isoformat(),
                )
                snapshot_state = "committed_unverified" if inserted else "existing_unverified"
                if inserted:
                    stage = "publish_push"
                    conn.push()
                stage = "verifier_connect"
                verifier = connect(path / "verify.db")
                connections.append(verifier)
                stage = "readback"
                stored = read_snapshot(verifier, run_id=run_id)
                if stored is None:
                    raise SnapshotError("readback_missing", "Cloud readback missing")
                if stored["content_hash"] != snapshot["content_hash"]:
                    raise SnapshotError("readback_content_mismatch", "Cloud readback mismatch")
                snapshot_state = "verified"
                print(f"PASS: {'published' if inserted else 'already published'} run_id={run_id} date={snapshot['report_date']}")
            else:
                stage = "read_schema"
                table = conn.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type = ? AND name = ?",
                    ("table", "juslag_daily_snapshots"),
                ).fetchone()[0]
                if table == 0:
                    raise SnapshotError("no_snapshot_table", "no published snapshots")
                stage = "read_snapshot"
                stored = read_snapshot(conn, report_date=args.date, run_id=args.run_id)
                if stored is None:
                    raise SnapshotError("snapshot_not_found", "snapshot not found")
                stage = "write_local_output"
                args.out.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    json.dump(stored, output, ensure_ascii=False, indent=2)
                    output.write("\n")
                print(f"PASS: read run_id={stored['run_id']} date={stored['report_date']} out={args.out}")
    except Exception as exc:  # noqa: BLE001 - never expose SDK messages containing credentials
        if isinstance(exc, SnapshotError) and exc.code == "run_id_content_conflict":
            snapshot_state = "not_written_this_attempt"
        diagnostic = {
            "stage": stage, "code": failure_code(exc),
            "exception_type": type(exc).__name__, "schema_state": schema_state,
            "snapshot_state": snapshot_state,
        }
        raise SystemExit(f"Turso {args.command} failed: " + json.dumps(diagnostic, sort_keys=True)) from None
    finally:
        for connection in reversed(connections):
            with suppress(Exception):
                connection.close()


if __name__ == "__main__":
    main()
