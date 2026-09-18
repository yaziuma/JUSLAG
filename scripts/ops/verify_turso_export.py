"""Verify a Turso export is intact and agrees with Git-owned daily reports."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from juslag.turso_reconcile import ROLLOUT_DATE, plan_reconciliation


def verify_export(
    db_path: Path, reports_dir: Path, history_path: Path, *, since: str = ROLLOUT_DATE,
) -> tuple[int, int]:
    if not db_path.is_file():
        raise ValueError("export file is missing")
    with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result != ("ok",):
            raise ValueError("export integrity check failed")
        repairs = plan_reconciliation(conn, reports_dir, history_path, since=since)
        count = conn.execute(
            "SELECT count(*) FROM juslag_daily_snapshots WHERE report_date >= ?", (since,),
        ).fetchone()[0]
    return count, len(repairs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--reports", type=Path, default=Path("data/reports"))
    parser.add_argument("--history", type=Path, default=Path("data/history.jsonl"))
    parser.add_argument("--since", default=ROLLOUT_DATE)
    args = parser.parse_args()
    try:
        row_count, mismatch_count = verify_export(
            args.db, args.reports, args.history, since=args.since,
        )
    except (sqlite3.Error, ValueError) as exc:
        raise SystemExit(f"Export verification failed: {type(exc).__name__}") from None
    print(f"Export: {row_count} snapshot row(s), {mismatch_count} date(s) differ from Git")
    if mismatch_count:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
