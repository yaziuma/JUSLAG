"""Create an attested manual order sheet from the newest pre-open report."""

from __future__ import annotations

import argparse
import hashlib
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
        if daily.get("signal_price_mode") != "adjusted":
            continue
        generated = datetime.fromisoformat(report["generated_at_utc"]).astimezone(JST)
        if generated > deadline or not daily.get("freshness", {}).get("freshness_ok"):
            continue
        candidates.append((generated, path, report))
    return candidates


def _candidate_local_reports(
    reports_dir: Path, as_of: str, deadline: datetime
) -> list[tuple[datetime, str, dict]]:
    candidates = []
    for path in sorted(reports_dir.glob("*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        daily = report.get("daily_signal", {})
        if daily.get("execution_target_jp_date") != as_of:
            continue
        if daily.get("signal_price_mode") != "adjusted":
            continue
        generated = datetime.fromisoformat(report["generated_at_utc"]).astimezone(JST)
        if generated > deadline or not daily.get("freshness", {}).get("freshness_ok"):
            continue
        candidates.append((generated, str(path), report))
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


def _local_prices_path(report_path: str) -> Path:
    report = Path(report_path)
    report_date = report.stem
    return (
        report.with_name(f"{report_date}.prices.csv")
        if report.parent.name == "signals"
        else Path("data/raw") / report_date / "prices_tail_raw.csv"
    )


def _prices_from_local(report_path: str, before_date: str) -> dict[str, float]:
    raw_path = _local_prices_path(report_path)
    frame = pd.read_csv(raw_path)
    frame = frame[(frame["ticker"].isin(JP_TICKERS)) & (frame["date"] < before_date)]
    latest = frame.sort_values("date").groupby("ticker").tail(1)
    if len(latest) != len(JP_TICKERS):
        raise ValueError("local sizing prices do not contain all 17 tickers")
    return {str(row.ticker): float(row.close) for row in latest.itertuples()}


def _file_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _is_jpx_session(day: str) -> bool:
    return not mcal.get_calendar("JPX").schedule(day, day).empty


def _matches_signal_model(report: dict, config: dict) -> bool:
    observed = (report.get("daily_signal") or {}).get("signal_model") or {}
    expected = config["signal_model"]
    try:
        return (
            int(observed.get("window_l")) == int(expected["window_l"])
            and int(observed.get("k_factors")) == int(expected["k_factors"])
            and float(observed.get("lambda_reg")) == float(expected["lambda_reg"])
            and float(observed.get("selection_quantile"))
            == float(expected["selection_quantile"])
        )
    except (TypeError, ValueError):
        return False


def run_preflight(
    *,
    as_of: str,
    now: datetime,
    ref: str,
    config_path: Path,
    state_path: Path,
    output_path: Path,
    status_path: Path,
    local_reports_dir: Path = Path("data/reports"),
    signal_reports_dir: Path = Path("data/manual_strategy/signals"),
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
        remote_candidates = [(*row, "git") for row in _candidate_reports(ref, as_of, deadline)]
        local_candidates = [
            (*row, "local")
            for row in _candidate_local_reports(local_reports_dir, as_of, deadline)
        ]
        signal_candidates = [
            (*row, "local_signal")
            for row in _candidate_local_reports(signal_reports_dir, as_of, deadline)
        ]
        candidates = remote_candidates + local_candidates + signal_candidates
        candidates = [row for row in candidates if _matches_signal_model(row[2], config)]
        if not candidates:
            raise ValueError(
                "no fresh adjusted pre-open report matches the manual signal model"
            )
        _, report_path, report, source_kind = max(
            candidates,
            key=lambda row: (
                pd.Timestamp(row[2]["daily_signal"]["signal_reference_us_date"]),
                row[0],
            ),
        )
        if source_kind == "git":
            source_commit = _git("rev-parse", ref).strip()
        else:
            source_commit = str((report.get("run_provenance") or {}).get("source_commit") or "")
            if len(source_commit) != 40:
                raise ValueError("local report lacks source commit provenance")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        prices = (
            _prices_from_ref(ref, report_path, as_of)
            if source_kind == "git"
            else _prices_from_local(report_path, as_of)
        )
        sheet = build_order_sheet(report, state, config, prices, as_of)
        sheet["preflight"] = {
            "status": "READY",
            "checked_at_jst": status["checked_at_jst"],
            "source_kind": source_kind,
            "source_ref": ref if source_kind == "git" else "local",
            "source_commit": source_commit,
            "source_report": report_path,
            "source_report_sha256": (
                _file_sha256(report_path) if source_kind != "git" else None
            ),
            "source_prices_sha256": (
                _file_sha256(str(_local_prices_path(report_path)))
                if source_kind == "local_signal"
                else None
            ),
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
            source_kind=source_kind,
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
    parser.add_argument(
        "--signal-reports-dir", type=Path, default=Path("data/manual_strategy/signals")
    )
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
        signal_reports_dir=args.signal_reports_dir,
    )
    print(json.dumps(status, ensure_ascii=False))
    if status["status"] == "BLOCKED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
