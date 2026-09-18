from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from juslag.turso_store import ensure_schema

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ops/verify_turso_export.py"
SPEC = importlib.util.spec_from_file_location("verify_turso_export", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_verify_empty_export(tmp_path: Path):
    db = tmp_path / "empty.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE juslag_daily_snapshots (report_date TEXT)")
    reports = tmp_path / "reports"
    reports.mkdir()
    assert module.verify_export(db, reports, tmp_path / "history.jsonl") == (0, 0)


def test_verify_missing_export(tmp_path: Path):
    with pytest.raises(ValueError, match="missing"):
        module.verify_export(tmp_path / "missing.db", tmp_path, tmp_path / "history.jsonl")


def test_verify_reports_missing_snapshot(tmp_path: Path):
    db = tmp_path / "export.db"
    with sqlite3.connect(db) as conn:
        ensure_schema(conn)
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "2026-09-18.json").write_text('{"date":"2026-09-18"}', encoding="utf-8")
    history = tmp_path / "history.jsonl"
    history.write_text(
        '{"jst_date":"2026-09-18","report":"data/reports/2026-09-18.json",'
        '"summary":"test","llm_status":"ok"}', encoding="utf-8",
    )
    assert module.verify_export(db, reports, history) == (0, 1)
