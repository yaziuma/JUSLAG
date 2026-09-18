"""Immutable daily research snapshots stored through Turso Sync."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def load_snapshot(report_path: Path, history_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report_date = report.get("date")
    if not isinstance(report_date, str) or not report_date:
        raise ValueError("report date is missing")
    summary_entry = None
    with history_path.open(encoding="utf-8") as history:
        for line in history:
            if line.strip():
                entry = json.loads(line)
                if entry.get("jst_date") == report_date:
                    summary_entry = entry
    if summary_entry is None:
        raise ValueError("matching summary is missing")
    if summary_entry.get("report") != f"data/reports/{report_date}.json":
        raise ValueError("summary report path differs")
    if not isinstance(summary_entry.get("summary"), str):
        raise ValueError("summary text is missing")
    if summary_entry.get("llm_status") not in {"ok", "failed", "skipped"}:
        raise ValueError("invalid llm status")
    report_json = canonical_json(report)
    summary_json = canonical_json({
        "summary": summary_entry["summary"],
        "llm_status": summary_entry["llm_status"],
    })
    combined = report_json + summary_json
    for name in ("JUSLAG_TURSO_AUTH_TOKEN", "JUSLAG_SLACK_WEBHOOK", "SITE_PASSWORD"):
        secret = os.getenv(name)
        if secret and secret in combined:
            raise ValueError("snapshot contains a configured secret")
    if re.search(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+", combined):
        raise ValueError("snapshot contains a Slack webhook")
    return {
        "report_date": report_date,
        "report_json": report_json,
        "summary": summary_entry["summary"],
        "llm_status": summary_entry["llm_status"],
        "content_hash": hashlib.sha256((report_json + "\n" + summary_json).encode()).hexdigest(),
        "generated_at_utc": str(report.get("generated_at_utc") or ""),
    }


def ensure_schema(conn: Any) -> None:
    exists = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type = ? AND name = ?",
        ("table", "juslag_daily_snapshots"),
    ).fetchone()[0]
    if exists:
        return
    conn.execute("""
        CREATE TABLE IF NOT EXISTS juslag_daily_snapshots (
            run_id TEXT PRIMARY KEY,
            report_date TEXT NOT NULL,
            source_commit TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            report_json TEXT NOT NULL,
            summary TEXT NOT NULL,
            llm_status TEXT NOT NULL,
            generated_at_utc TEXT NOT NULL,
            published_at_utc TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS juslag_daily_snapshots_by_date
        ON juslag_daily_snapshots(report_date, published_at_utc)
    """)
    conn.commit()


def publish_snapshot(
    conn: Any, snapshot: dict[str, Any], *, run_id: str, source_commit: str,
    published_at_utc: str,
) -> bool:
    if not run_id or not source_commit:
        raise ValueError("run_id and source_commit are required")
    existing = conn.execute(
        "SELECT content_hash FROM juslag_daily_snapshots WHERE run_id = ?", (run_id,),
    ).fetchone()
    if existing is not None:
        if existing[0] != snapshot["content_hash"]:
            raise ValueError("run_id already exists with different content")
        return False
    conn.execute(
        """INSERT INTO juslag_daily_snapshots
        (run_id, report_date, source_commit, content_hash, report_json, summary,
         llm_status, generated_at_utc, published_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id, snapshot["report_date"], source_commit, snapshot["content_hash"],
            snapshot["report_json"], snapshot["summary"], snapshot["llm_status"],
            snapshot["generated_at_utc"], published_at_utc,
        ),
    )
    conn.commit()
    return True


def read_snapshot(
    conn: Any, *, report_date: str | None = None, run_id: str | None = None,
) -> dict[str, Any] | None:
    if run_id is not None:
        row = conn.execute(
            """SELECT run_id, report_date, source_commit, content_hash, report_json,
                      summary, llm_status, generated_at_utc, published_at_utc
               FROM juslag_daily_snapshots WHERE run_id = ?""", (run_id,),
        ).fetchone()
    elif report_date is None:
        row = conn.execute(
            """SELECT run_id, report_date, source_commit, content_hash, report_json,
                      summary, llm_status, generated_at_utc, published_at_utc
               FROM juslag_daily_snapshots
               ORDER BY report_date DESC, published_at_utc DESC, run_id DESC LIMIT 1"""
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT run_id, report_date, source_commit, content_hash, report_json,
                      summary, llm_status, generated_at_utc, published_at_utc
               FROM juslag_daily_snapshots WHERE report_date = ?
               ORDER BY published_at_utc DESC, run_id DESC LIMIT 1""",
            (report_date,),
        ).fetchone()
    if row is None:
        return None
    keys = (
        "run_id", "report_date", "source_commit", "content_hash", "report_json",
        "summary", "llm_status", "generated_at_utc", "published_at_utc",
    )
    result = dict(zip(keys, row))
    report = json.loads(result.pop("report_json"))
    result["report"] = report
    expected = hashlib.sha256((canonical_json(report) + "\n" + canonical_json({
        "summary": result["summary"], "llm_status": result["llm_status"],
    })).encode()).hexdigest()
    if expected != result["content_hash"]:
        raise ValueError("snapshot hash mismatch")
    return result
