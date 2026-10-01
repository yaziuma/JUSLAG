#!/usr/bin/env python3
"""Build the smallest fresh signal snapshot required by manual preflight."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from juslag.cache import PriceCache
from juslag.config import AppConfig, JP_TICKERS, US_TICKERS
from juslag.data_loader import fetch_data
from juslag.services.daily_signal import run_daily_signal_service

JST = ZoneInfo("Asia/Tokyo")
ROOT = Path(__file__).resolve().parents[2]


def _source_commit() -> str:
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""
    return value if len(value) == 40 else ""


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="JST target date (YYYY-MM-DD)")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/manual_strategy/signals")
    )
    args = parser.parse_args()

    actual_now = datetime.now(JST)
    target_date = args.date or actual_now.date().isoformat()
    analysis_now = datetime.combine(
        datetime.fromisoformat(target_date).date(), actual_now.time(), tzinfo=JST
    )
    sample_end = (datetime.fromisoformat(target_date).date() + timedelta(days=1)).isoformat()
    cfg = AppConfig.load(ROOT / "config" / "app.yaml")
    cache = PriceCache()

    fetch_data(
        list(US_TICKERS), list(JP_TICKERS), cfg.daily.sample_start, sample_end,
        price_mode="raw", cache=cache, refresh=True,
    )
    signal = run_daily_signal_service(
        cfg,
        cache,
        now_jst=analysis_now,
        actual_run_jst=actual_now,
        log_path=None,
        refresh_prices=False,
    )

    since = (datetime.fromisoformat(target_date).date() - timedelta(days=7)).isoformat()
    prices = cache.export_tail(list(US_TICKERS) + list(JP_TICKERS), since, "raw")
    prices_path = args.output_dir / f"{target_date}.prices.csv"
    _write_atomic(prices_path, prices.to_csv(index=False))

    payload = {
        "schema_version": 1,
        "date": target_date,
        "snapshot_kind": "manual_strategy_preflight_signal",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_provenance": {
            "source_commit": _source_commit(),
            "run_started_at_utc": actual_now.astimezone(timezone.utc).isoformat(),
            "analysis_as_of_jst": analysis_now.isoformat(),
            "input_snapshot_sha256": signal.get("input_snapshot_sha256"),
        },
        "daily_signal": signal,
    }
    report_path = args.output_dir / f"{target_date}.json"
    _write_atomic(report_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"SIGNAL_SNAPSHOT_PATH={report_path}")


if __name__ == "__main__":
    main()
