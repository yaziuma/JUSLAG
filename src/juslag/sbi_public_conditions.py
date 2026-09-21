from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from juslag.config import JP_TICKERS

HYPER_DIFF_URL = (
    "https://site0.sbisec.co.jp/marble/domestic/top/hssProductDiff.do"
    "?int_pr1=150110_dstock_tool%3Amarginsellhyper_tmn_52"
)
USER_AGENT = "JUSLAG-research-evidence/1.0"


def _last_number(text: str) -> float | None:
    values = re.findall(r"\d[\d,]*(?:\.\d+)?", text)
    return float(values[-1].replace(",", "")) if values else None


def parse_hyper_diff(raw: bytes) -> dict[str, Any]:
    text = raw.decode("cp932")
    if "HYPER空売り銘柄　前日比較" not in text:
        raise ValueError("SBI HYPER difference marker not found")
    match = re.search(r"約定基準：前日(?:&nbsp;|\s)*(\d{4}/\d{2}/\d{2}).*?当日(?:&nbsp;|\s)*(\d{4}/\d{2}/\d{2})", text, re.S)
    if not match:
        raise ValueError("SBI applicable dates not found")

    soup = BeautifulSoup(text, "html.parser")
    changes: dict[str, dict[str, Any]] = {}
    for row in soup.select('[role="row"].seeds-table-row'):
        cells = row.select(':scope > [role="cell"]')
        if len(cells) < 4:
            continue
        code_match = re.search(r"\b(\d{4}|\d{3}[A-Z])\b", cells[1].get_text(" ", strip=True))
        if not code_match:
            continue
        code = code_match.group(1)
        change_label = cells[0].get_text(" ", strip=True) or "terms_changed"
        name_node = cells[1].select_one("a")
        changes[code] = {
            "change_type": change_label,
            "name": name_node.get_text(" ", strip=True) if name_node else None,
            "hyper_fee_yen_per_share_day": _last_number(cells[2].get_text(" ", strip=True)),
            "max_position_units": _last_number(cells[3].get_text(" ", strip=True)),
        }

    return {
        "previous_session": match.group(1).replace("/", "-"),
        "applicable_session": match.group(2).replace("/", "-"),
        "changes": changes,
    }


def build_snapshot(raw: bytes, observed_at: datetime, source_url: str = HYPER_DIFF_URL) -> dict[str, Any]:
    parsed = parse_hyper_diff(raw)
    rows = []
    for ticker, sector in JP_TICKERS.items():
        code = ticker.removesuffix(".T")
        change = parsed["changes"].get(code)
        rows.append({
            "ticker": ticker,
            "sector": sector,
            "public_change_status": change["change_type"] if change else "not_present_in_change_page",
            "hyper_status": "changed" if change else "unknown_public_diff_only",
            "hyper_fee_yen_per_share_day": change["hyper_fee_yen_per_share_day"] if change else None,
            "max_position_units": change["max_position_units"] if change else None,
            "new_short_allowed": None,
            "collection_status": "public_change_observed" if change else "full_list_requires_login",
        })
    return {
        "schema_version": 1,
        "evidence_type": "sbi_public_hyper_difference",
        "observed_at_jst": observed_at.isoformat(),
        "previous_session": parsed["previous_session"],
        "applicable_session": parsed["applicable_session"],
        "source_url": source_url,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_encoding": "cp932",
        "source_scope": "changes_only_full_lists_require_login",
        "target_ticker_count": len(rows),
        "changed_target_count": sum(row["hyper_status"] == "changed" for row in rows),
        "rows": rows,
    }


def fetch_source(url: str = HYPER_DIFF_URL, timeout: float = 30) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS SBI URL
        final_url = response.geturl()
        raw = response.read()
    if not final_url.startswith("https://site0.sbisec.co.jp/"):
        raise ValueError("unexpected SBI redirect")
    return raw


def write_snapshot(snapshot: dict[str, Any], output_root: Path) -> Path:
    session = snapshot["applicable_session"]
    observed = datetime.fromisoformat(snapshot["observed_at_jst"])
    suffix = observed.strftime("%Y%m%dT%H%M%S%z")
    destination = output_root / session / f"sbi_public_conditions_{suffix}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


def audit_snapshots(output_root: Path, start_session: str) -> dict[str, Any]:
    sessions: dict[str, dict[str, Any]] = {}
    invalid_files: list[str] = []
    valid_files = 0
    for path in sorted(output_root.glob("*/*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            session = item["applicable_session"]
            rows = item["rows"]
            valid = (
                item.get("schema_version") == 1
                and item.get("source_scope") == "changes_only_full_lists_require_login"
                and len(rows) == len(JP_TICKERS)
                and {row["ticker"] for row in rows} == set(JP_TICKERS)
            )
            if session >= start_session and valid:
                sessions[session] = item
                valid_files += 1
            elif session >= start_session:
                invalid_files.append(str(path))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            invalid_files.append(str(path))
    return {
        "observed_sessions": len(sessions),
        "latest_session": max(sessions) if sessions else None,
        "valid_snapshot_files": valid_files,
        "invalid_files": invalid_files,
        "target_ticker_count": len(JP_TICKERS),
        "availability_known_from_public_source": False,
        "broker_execution_records_present": False,
        "informational_only": True,
    }
