"""Audit or repair Turso daily snapshots against Git-owned reports."""
from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from juslag.turso_reconcile import ROLLOUT_DATE, plan_reconciliation, repair_snapshots, verify_repairs
from turso_daily import connect


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=ROLLOUT_DATE)
    parser.add_argument("--reports", type=Path, default=Path("data/reports"))
    parser.add_argument("--history", type=Path, default=Path("data/history.jsonl"))
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--max-repairs", type=int, default=10)
    args = parser.parse_args()
    if args.max_repairs < 1:
        parser.error("--max-repairs must be positive")
    if args.repair and os.getenv("JUSLAG_WRITE_TURSO", "").lower() not in {"1", "true"}:
        raise SystemExit("Turso writes disabled; set JUSLAG_WRITE_TURSO=1")
    try:
        with tempfile.TemporaryDirectory(prefix="juslag-turso-reconcile-") as root:
            root_path = Path(root)
            conn = connect(root_path / "audit.db")
            repairs = plan_reconciliation(conn, args.reports, args.history, since=args.since)
            print(f"Audit: {len(repairs)} date(s) require repair since {args.since}")
            if not repairs:
                return
            for item in repairs:
                print(f"  {item['snapshot']['report_date']}: {item['reason']}")
            if not args.repair:
                raise SystemExit(2)
            if len(repairs) > args.max_repairs:
                raise ValueError("repair count exceeds --max-repairs")
            source_commit = os.getenv("GITHUB_SHA") or subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True,
            ).strip()
            repair_snapshots(
                conn, repairs, source_commit=source_commit,
                published_at_utc=datetime.now(timezone.utc).isoformat(),
            )
            verifier = connect(root_path / "verify.db")
            verify_repairs(verifier, repairs)
            print(f"PASS: reconciled {len(repairs)} date(s)")
    except Exception as exc:  # noqa: BLE001 - SDK errors may contain credentials
        raise SystemExit(f"Turso reconciliation failed: {type(exc).__name__}") from None


if __name__ == "__main__":
    main()
