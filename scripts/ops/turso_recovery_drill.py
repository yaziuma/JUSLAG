"""Exercise Turso reconciliation against a disposable local Sync server."""
from __future__ import annotations

import argparse
import json
import socket
import tempfile
from pathlib import Path

import turso.sync

from juslag.turso_reconcile import plan_reconciliation, repair_snapshots, verify_repairs
from juslag.turso_store import publish_snapshot
from turso_sync_poc import local_server


DATE = "2026-09-18"
STAMP_1 = "2026-09-18T01:00:00Z"
STAMP_2 = "2026-09-18T02:00:00Z"
STAMP_3 = "2026-09-18T03:00:00Z"


def write_fixture(root: Path, summary: str) -> tuple[Path, Path]:
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    (reports / f"{DATE}.json").write_text(json.dumps({"date": DATE}), encoding="utf-8")
    history = root / "history.jsonl"
    history.write_text(json.dumps({
        "jst_date": DATE, "report": f"data/reports/{DATE}.json",
        "summary": summary, "llm_status": "ok",
    }), encoding="utf-8")
    return reports, history


def client(path: Path, url: str):
    conn = turso.sync.connect(path=str(path), remote_url=url, bootstrap_if_empty=False)
    conn.pull()
    return conn


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-bin", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="juslag-turso-recovery-") as directory:
        root = Path(directory)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        database, log = root / "server.db", root / "server.log"
        reports, history = write_fixture(root, "initial")
        with local_server(args.server_bin, database, port, log):
            writer = client(root / "writer.db", url)
            missing = plan_reconciliation(writer, reports, history)
            assert len(missing) == 1 and missing[0]["reason"] == "missing"
            repair_snapshots(writer, missing, source_commit="drill", published_at_utc=STAMP_1)
            verify_repairs(client(root / "verify-missing.db", url), missing)
            assert plan_reconciliation(writer, reports, history) == []

            write_fixture(root, "corrected")
            different = plan_reconciliation(writer, reports, history)
            assert len(different) == 1 and different[0]["reason"] == "different"
            repair_snapshots(writer, different, source_commit="drill", published_at_utc=STAMP_2)
            verify_repairs(client(root / "verify-different.db", url), different)
            assert writer.execute("SELECT count(*) FROM juslag_daily_snapshots").fetchone()[0] == 2

            write_fixture(root, "after-outage")
            pending = plan_reconciliation(writer, reports, history)

        publish_snapshot(
            writer, pending[0]["snapshot"], run_id=pending[0]["run_id"],
            source_commit="drill", published_at_utc=STAMP_3,
        )
        try:
            writer.push()
        except Exception:  # noqa: BLE001 - the server is intentionally stopped
            pass
        else:
            raise AssertionError("push unexpectedly succeeded while offline")

        with local_server(args.server_bin, database, port, log):
            repair_snapshots(writer, pending, source_commit="drill", published_at_utc=STAMP_3)
            fresh = client(root / "verify-retry.db", url)
            verify_repairs(fresh, pending)
            assert fresh.execute("SELECT count(*) FROM juslag_daily_snapshots").fetchone()[0] == 3
            assert plan_reconciliation(fresh, reports, history) == []
        print("PASS: missing, different, offline push retry, fresh readback, no duplicate")


if __name__ == "__main__":
    main()
