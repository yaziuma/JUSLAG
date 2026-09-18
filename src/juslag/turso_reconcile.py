"""Compare Git-owned daily reports with the latest Turso snapshots."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from juslag.turso_store import load_snapshot, read_snapshot


ROLLOUT_DATE = "2026-09-18"


def plan_reconciliation(
    conn: Any, reports_dir: Path, history_path: Path, *, since: str = ROLLOUT_DATE,
) -> list[dict[str, Any]]:
    if not reports_dir.is_dir():
        raise ValueError("reports directory is missing")
    if len(since) != 10 or since[4] != "-" or since[7] != "-":
        raise ValueError("since must be YYYY-MM-DD")
    from datetime import date

    date.fromisoformat(since)
    table_exists = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type = ? AND name = ?",
        ("table", "juslag_daily_snapshots"),
    ).fetchone()[0]
    repairs = []
    for path in sorted(reports_dir.glob("????-??-??.json")):
        if path.stem < since:
            continue
        date.fromisoformat(path.stem)
        snapshot = load_snapshot(path, history_path)
        if snapshot["report_date"] != path.stem:
            raise ValueError("report date differs from filename")
        current = read_snapshot(conn, report_date=path.stem) if table_exists else None
        if current is None or current["content_hash"] != snapshot["content_hash"]:
            predecessor = current["run_id"] if current else "missing"
            fingerprint = hashlib.sha256(predecessor.encode()).hexdigest()[:12]
            repairs.append({
                "snapshot": snapshot,
                "reason": "missing" if current is None else "different",
                "run_id": f"reconcile:{path.stem}:{snapshot['content_hash'][:16]}:{fingerprint}",
            })
    return repairs
