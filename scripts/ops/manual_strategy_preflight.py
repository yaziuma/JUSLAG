"""Create an attested manual order sheet from the newest pre-open report."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, time
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

from juslag.config import JP_TICKERS
from juslag.manual_strategy import build_order_sheet, fingerprint, load_manual_config

JST = ZoneInfo("Asia/Tokyo")


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return result.stdout


def _read_json_from_ref(ref: str, path: str) -> dict:
    return json.loads(_git("show", f"{ref}:{path}"))


def _candidate_reports(
    ref: str, as_of: str, deadline: datetime
) -> list[tuple[datetime, str, dict]]:
    paths = _git("ls-tree", "-r", "--name-only", ref, "data/reports").splitlines()
    candidates = []
    for path in paths:
        if not path.endswith(".json"):
            continue
        report = _read_json_from_ref(ref, path)
        daily = report.get("daily_signal", {})
        if daily.get("execution_target_jp_date") != as_of:
            continue
        generated = datetime.fromisoformat(report["generated_at_utc"]).astimezone(JST)
        if generated > deadline or not daily.get("freshness", {}).get("freshness_ok"):
            continue
        candidates.append((generated, path, report))
    return candidates


def _prices_from_ref(ref: str, report_path: str, before_date: str) -> dict[str, float]:
    report_date = Path(report_path).stem
    raw_path = f"data/raw/{report_date}/prices_tail_raw.csv"
    frame = pd.read_csv(StringIO(_git("show", f"{ref}:{raw_path}")))
    frame = frame[(frame["ticker"].isin(JP_TICKERS)) & (frame["date"] < before_date)]
    latest = frame.sort_values("date").groupby("ticker").tail(1)
    if len(latest) != len(JP_TICKERS):
        raise ValueError("sizing prices do not contain all 17 tickers")
    return {str(row.ticker): float(row.close) for row in latest.itertuples()}


def _write_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _is_jpx_session(day: str) -> bool:
    return not mcal.get_calendar("JPX").schedule(day, day).empty


def run_preflight(
    *,
    as_of: str,
    now: datetime,
    ref: str,
    config_path: Path,
    state_path: Path,
    output_path: Path,
    status_path: Path,
) -> dict:
    config = load_manual_config(config_path)
    status: dict = {
        "schema_version": 1,
        "strategy_id": config["strategy_id"],
        "as_of": as_of,
        "checked_at_jst": now.astimezone(JST).isoformat(),
        "status": "BLOCKED",
    }
    try:
        if not _is_jpx_session(as_of):
            status.update(status="SKIP", reason="not_a_jpx_session")
            return status
        deadline_clock = time.fromisoformat(config["execution"]["entry_order_deadline_jst"])
        deadline = datetime.combine(datetime.fromisoformat(as_of).date(), deadline_clock, JST)
        if now.astimezone(JST) > deadline:
            raise ValueError("entry deadline has passed")
        candidates = _candidate_reports(ref, as_of, deadline)
        if not candidates:
            raise ValueError("no fresh pre-open report targets this JPX session")
        _, report_path, report = max(
            candidates,
            key=lambda row: (
                pd.Timestamp(row[2]["daily_signal"]["signal_reference_us_date"]),
                row[0],
            ),
        )
        source_commit = _git("rev-parse", ref).strip()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        prices = _prices_from_ref(ref, report_path, as_of)
        sheet = build_order_sheet(report, state, config, prices, as_of)
        sheet["preflight"] = {
            "status": "READY",
            "checked_at_jst": status["checked_at_jst"],
            "source_ref": ref,
            "source_commit": source_commit,
            "source_report": report_path,
            "source_report_generated_at_utc": report["generated_at_utc"],
        }
        sheet.pop("sheet_sha256", None)
        sheet["sheet_sha256"] = fingerprint(sheet)
        _write_atomic(output_path, sheet)
        status.update(
            status="READY",
            action=sheet["action"],
            order_sheet=str(output_path),
            sheet_sha256=sheet["sheet_sha256"],
            source_commit=source_commit,
            source_report=report_path,
        )
        return status
    except Exception as exc:
        status["reason"] = str(exc)
        return status
    finally:
        _write_atomic(status_path, status)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default=datetime.now(JST).date().isoformat())
    parser.add_argument("--now-jst", help="test override in ISO-8601 format")
    parser.add_argument("--source-ref", default="origin/main")
    parser.add_argument("--config", type=Path, default=Path("config/manual_strategy.yaml"))
    parser.add_argument("--state", type=Path, default=Path("data/manual_strategy/state.json"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--status", type=Path)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    now = (
        datetime.fromisoformat(args.now_jst).astimezone(JST) if args.now_jst else datetime.now(JST)
    )
    output = args.output or Path(f"data/manual_strategy/orders/{args.as_of}-entry.json")
    status_path = args.status or Path(f"data/manual_strategy/preflight/{args.as_of}.json")
    if args.fetch:
        subprocess.run(["git", "fetch", "origin", "main"], check=True)
    status = run_preflight(
        as_of=args.as_of,
        now=now,
        ref=args.source_ref,
        config_path=args.config,
        state_path=args.state,
        output_path=output,
        status_path=status_path,
    )
    print(json.dumps(status, ensure_ascii=False))
    if status["status"] == "BLOCKED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
