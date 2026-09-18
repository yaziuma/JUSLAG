import json
import sqlite3

import pytest

from juslag.turso_store import ensure_schema, load_snapshot, publish_snapshot, read_snapshot


def test_snapshot_publish_read_and_idempotency(tmp_path) -> None:
    date = "2026-09-18"
    report_path = tmp_path / f"{date}.json"
    history_path = tmp_path / "history.jsonl"
    report = {"date": date, "generated_at_utc": "2026-09-18T00:00:00Z", "signal": {"n": 1}}
    report_path.write_text(json.dumps(report), encoding="utf-8")
    entries = [
        {"jst_date": date, "report": f"data/reports/{date}.json", "summary": "old", "llm_status": "ok"},
        {"jst_date": date, "report": f"data/reports/{date}.json", "summary": "latest", "llm_status": "failed"},
    ]
    history_path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
    snapshot = load_snapshot(report_path, history_path)
    assert snapshot["summary"] == "latest"

    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    assert publish_snapshot(
        conn, snapshot, run_id="actions:1:1", source_commit="abc", published_at_utc="2026-09-18T01:00Z",
    )
    assert not publish_snapshot(
        conn, snapshot, run_id="actions:1:1", source_commit="abc", published_at_utc="2026-09-18T01:00Z",
    )
    assert read_snapshot(conn, report_date=date)["report"] == report

    changed = dict(snapshot, content_hash="0" * 64)
    with pytest.raises(ValueError, match="different content"):
        publish_snapshot(
            conn, changed, run_id="actions:1:1", source_commit="abc",
            published_at_utc="2026-09-18T01:00Z",
        )


def test_read_detects_tampered_row() -> None:
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    conn.execute(
        """INSERT INTO juslag_daily_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("r1", "2026-09-18", "abc", "0" * 64, '{"date":"2026-09-18"}',
         "summary", "ok", "2026-09-18T00:00Z", "2026-09-18T01:00Z"),
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        read_snapshot(conn, run_id="r1")


def test_snapshot_requires_matching_summary(tmp_path) -> None:
    report_path = tmp_path / "report.json"
    history_path = tmp_path / "history.jsonl"
    report_path.write_text('{"date":"2026-09-18"}', encoding="utf-8")
    history_path.write_text('{"jst_date":"2026-09-17"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="matching summary"):
        load_snapshot(report_path, history_path)


def test_snapshot_rejects_secret_in_summary(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "report.json"
    history_path = tmp_path / "history.jsonl"
    report_path.write_text('{"date":"2026-09-18"}', encoding="utf-8")
    history_path.write_text(json.dumps({
        "jst_date": "2026-09-18", "report": "data/reports/2026-09-18.json",
        "summary": "contains secret-value", "llm_status": "ok",
    }), encoding="utf-8")
    monkeypatch.setenv("JUSLAG_TURSO_AUTH_TOKEN", "secret-value")
    with pytest.raises(ValueError, match="configured secret"):
        load_snapshot(report_path, history_path)
