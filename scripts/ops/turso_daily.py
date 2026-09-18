"""Publish finalized JUSLAG research to Turso or read it back."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from juslag.turso_store import ensure_schema, load_snapshot, publish_snapshot, read_snapshot


def connect(path: Path):
    import turso.sync

    url = os.environ["JUSLAG_TURSO_DATABASE_URL"]
    token = os.environ["JUSLAG_TURSO_AUTH_TOKEN"]
    if not url.startswith(("libsql://", "turso://")):
        raise ValueError("unsupported Turso URL scheme")
    conn = turso.sync.connect(
        path=str(path), remote_url=url, auth_token=token, bootstrap_if_empty=False,
    )
    conn.pull()
    return conn


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("--report", type=Path, required=True)
    publish.add_argument("--history", type=Path, default=Path("data/history.jsonl"))
    publish.add_argument("--run-id")
    read = commands.add_parser("read")
    read.add_argument("--date")
    read.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "publish" and os.getenv("JUSLAG_WRITE_TURSO", "").lower() not in {"1", "true"}:
        raise SystemExit("Turso writes disabled; set JUSLAG_WRITE_TURSO=1")

    try:
        with tempfile.TemporaryDirectory(prefix="juslag-turso-daily-") as root:
            path = Path(root)
            conn = connect(path / "writer.db")
            if args.command == "publish":
                snapshot = load_snapshot(args.report, args.history)
                source_commit = os.getenv("GITHUB_SHA") or subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True,
                ).strip()
                run_id = args.run_id or (
                    f"actions:{os.environ['GITHUB_RUN_ID']}:{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
                    if os.getenv("GITHUB_RUN_ID") else f"local:{uuid.uuid4().hex}"
                )
                ensure_schema(conn)
                conn.push()
                inserted = publish_snapshot(
                    conn, snapshot, run_id=run_id, source_commit=source_commit,
                    published_at_utc=datetime.now(timezone.utc).isoformat(),
                )
                if inserted:
                    conn.push()
                verifier = connect(path / "verify.db")
                stored = read_snapshot(verifier, run_id=run_id)
                if stored is None or stored["content_hash"] != snapshot["content_hash"]:
                    raise ValueError("Cloud readback mismatch")
                print(f"PASS: {'published' if inserted else 'already published'} run_id={run_id} date={snapshot['report_date']}")
            else:
                table = conn.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type = ? AND name = ?",
                    ("table", "juslag_daily_snapshots"),
                ).fetchone()[0]
                if table == 0:
                    raise ValueError("no published snapshots")
                stored = read_snapshot(conn, report_date=args.date)
                if stored is None:
                    raise ValueError("snapshot not found")
                args.out.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    json.dump(stored, output, ensure_ascii=False, indent=2)
                    output.write("\n")
                print(f"PASS: read run_id={stored['run_id']} date={stored['report_date']} out={args.out}")
    except Exception as exc:  # noqa: BLE001 - never expose SDK errors containing credentials
        raise SystemExit(f"Turso {args.command} failed: {type(exc).__name__}") from None


if __name__ == "__main__":
    main()
