from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from juslag.report_registry import template_map
from juslag.report_templates import GeneratedReport, build_report_file_path, default_common_conditions, render_standard_markdown


_RANGE_PAIRS: list[tuple[str, str]] = [
    ("from_date", "to_date"),
    ("quantile_q_from", "quantile_q_to"),
    ("window_l_from", "window_l_to"),
    ("min_long_signal_from", "min_long_signal_to"),
    ("max_short_signal_from", "max_short_signal_to"),
    ("min_signal_spread_from", "min_signal_spread_to"),
]


def _to_float(v: Any) -> float:
    return float(v)


def validate_conditions(conditions: dict[str, Any]) -> None:
    for left, right in _RANGE_PAIRS:
        left_exists = left in conditions and conditions[left] not in (None, "")
        right_exists = right in conditions and conditions[right] not in (None, "")
        if left_exists != right_exists:
            raise ValueError(f"{left} and {right} must be provided together")
        if not left_exists:
            continue
        if left.endswith("date"):
            left_value = datetime.fromisoformat(str(conditions[left]))
            right_value = datetime.fromisoformat(str(conditions[right]))
        else:
            left_value = _to_float(conditions[left])
            right_value = _to_float(conditions[right])
        if left_value > right_value:
            raise ValueError(f"invalid range: {left} must be <= {right}")


def history_path() -> Path:
    p = Path("outputs/generated_reports_history.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_generated_history(limit: int = 30) -> list[dict[str, Any]]:
    p = history_path()
    if not p.exists():
        return []
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return list(reversed(rows[-limit:]))


def append_generated_history(row: dict[str, Any]) -> None:
    with history_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def generate_report(template_id: str, params: dict[str, Any], save_report: bool = False, report_name: str | None = None) -> GeneratedReport:
    tmap = template_map()
    if template_id not in tmap:
        raise ValueError(f"unknown template_id: {template_id}")

    merged = {**default_common_conditions(), **params}
    validate_conditions(merged)
    template = tmap[template_id]

    now = datetime.now()
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S")
    markdown = render_standard_markdown(template, merged, generated_at)

    report_path: str | None = None
    report_url: str | None = None
    if save_report:
        target = build_report_file_path(Path("docs/reports/standardized"), template_id, report_name, now)
        target.write_text(markdown, encoding="utf-8")
        report_path = str(target)
        report_url = f"/reports/standardized?file={target.name}"

    report_title = report_name or f"{template_id}_study_{now.strftime('%Y%m%d_%H%M%S')}"
    report = GeneratedReport(
        template_id=template_id,
        report_title=report_title,
        report_markdown=markdown,
        report_html="",
        conditions=merged,
        generated_at=generated_at,
        report_path=report_path,
        report_url=report_url,
    )
    append_generated_history(
        {
            "template_id": template_id,
            "generated_at": generated_at,
            "report_name": report_title,
            "report_path": report_path,
            "report_url": report_url,
            "conditions_json": merged,
        }
    )
    return report


def report_to_payload(report: GeneratedReport) -> dict[str, Any]:
    return asdict(report)
