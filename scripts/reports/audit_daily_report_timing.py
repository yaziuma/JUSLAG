"""Audit whether daily reports use opening-gap decisions before JP market open."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pandas as pd
import pandas_market_calendars as mcal


def audit_report(report: dict, jp_open_by_date: dict[str, pd.Timestamp]) -> dict:
    history = report.get("history_entry") or {}
    target = history.get("exec_jp_date")
    generated = pd.Timestamp(report["generated_at_utc"]).tz_convert("Asia/Tokyo")
    market_open = jp_open_by_date.get(target) if target else None
    gap = (history.get("strategy_context") or {}).get("open_gap")
    if market_open is None:
        timing = "no_target_session"
    elif generated < market_open:
        timing = "before_open"
    elif generated.normalize() > market_open.normalize():
        timing = "after_target_day"
    else:
        timing = "after_open"
    return {
        "report_date": str(report.get("date") or ""),
        "target_jp_date": str(target or ""),
        "generated_jst": generated.isoformat(),
        "target_open_jst": market_open.isoformat() if market_open is not None else "",
        "timing": timing,
        "tradeable": bool(history.get("tradeable")),
        "selected_strategy": str(history.get("selected_strategy") or ""),
        "open_gap_recorded": gap is not None,
        "open_gap": gap if gap is not None else "",
    }


def target_price_rows(raw_csv: Path, target_date: str) -> int | None:
    if not raw_csv.exists() or not target_date:
        return None
    with raw_csv.open(newline="", encoding="utf-8") as file:
        return sum(row["date"] == target_date and row["ticker"].endswith(".T")
                   for row in csv.DictReader(file))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, default=Path("data/reports"))
    parser.add_argument("--out", type=Path, default=Path("/tmp/juslag_daily_report_timing.csv"))
    args = parser.parse_args()
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.reports.glob("*.json"))]
    if not reports:
        raise SystemExit("No reports")
    dates = [pd.Timestamp(report["date"]) for report in reports]
    schedule = mcal.get_calendar("JPX").schedule(
        start_date=min(dates) - pd.Timedelta(days=7),
        end_date=max(dates) + pd.Timedelta(days=7),
    )
    jp_open = {
        pd.Timestamp(day).date().isoformat(): opening.tz_convert("Asia/Tokyo")
        for day, opening in schedule["market_open"].items()
    }
    rows = []
    for report in reports:
        row = audit_report(report, jp_open)
        raw_csv = args.reports.parent / "raw" / row["report_date"] / "prices_tail_raw.csv"
        raw_rows = target_price_rows(raw_csv, row["target_jp_date"])
        row["raw_target_price_rows"] = raw_rows if raw_rows is not None else ""
        rows.append(row)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    preopen_tradeable_gap = sum(
        row["timing"] == "before_open" and row["tradeable"] and row["open_gap_recorded"]
        for row in rows
    )
    after_target = sum(row["timing"] == "after_target_day" for row in rows)
    preopen_gap_without_raw = sum(
        row["timing"] == "before_open" and row["open_gap_recorded"]
        and row["raw_target_price_rows"] == 0 for row in rows
    )
    print(f"reports={len(rows)} preopen_tradeable_with_gap={preopen_tradeable_gap} "
          f"preopen_gap_without_raw_target={preopen_gap_without_raw} "
          f"after_target_day={after_target} out={args.out}")


if __name__ == "__main__":
    main()
