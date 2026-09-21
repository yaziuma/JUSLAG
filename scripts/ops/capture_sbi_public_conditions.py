"""Capture SBI's public HYPER short-condition differences for JUSLAG ETFs."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from juslag.sbi_public_conditions import build_snapshot, fetch_source, write_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("data/sbi_execution_conditions"))
    parser.add_argument("--source-file", type=Path, help="Parse a saved CP932 HTML file instead of downloading")
    parser.add_argument("--observed-at", help="ISO-8601 timestamp; defaults to the actual JST clock")
    args = parser.parse_args()
    observed_at = (
        datetime.fromisoformat(args.observed_at)
        if args.observed_at
        else datetime.now(ZoneInfo("Asia/Tokyo"))
    )
    if observed_at.tzinfo is None:
        parser.error("--observed-at must include a timezone")
    raw = args.source_file.read_bytes() if args.source_file else fetch_source()
    snapshot = build_snapshot(raw, observed_at)
    destination = write_snapshot(snapshot, args.output_root)
    print(json.dumps({
        "path": str(destination),
        "applicable_session": snapshot["applicable_session"],
        "target_tickers": snapshot["target_ticker_count"],
        "changed_targets": snapshot["changed_target_count"],
        "source_sha256": snapshot["source_sha256"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

