from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from juslag.config import JP_TICKERS
from juslag.sbi_public_conditions import audit_snapshots, build_snapshot, parse_hyper_diff, write_snapshot


def _fixture(marker: str = "HYPER空売り銘柄　前日比較") -> bytes:
    html = f"""
    <html><body>
      <h1>{marker}</h1>
      <div>約定基準：前日&nbsp;2026/09/18 → 当日&nbsp;2026/09/24</div>
      <ul role="table">
        <li class="seeds-table-row" role="row">
          <div role="cell"><span>新規取扱</span></div>
          <div role="cell"><a>食品ETF</a><li>1617</li></div>
          <div role="cell"><ul><li>0.5 円</li><li>→</li><li>0.7 円</li></ul></div>
          <div role="cell"><ul><li>100 単元</li><li>→</li><li>120 単元</li></ul></div>
        </li>
      </ul>
    </body></html>
    """
    return html.encode("cp932")


def test_parse_hyper_diff_extracts_current_values() -> None:
    result = parse_hyper_diff(_fixture())
    assert result["previous_session"] == "2026-09-18"
    assert result["applicable_session"] == "2026-09-24"
    assert result["changes"]["1617"]["change_type"] == "新規取扱"
    assert result["changes"]["1617"]["hyper_fee_yen_per_share_day"] == 0.7
    assert result["changes"]["1617"]["max_position_units"] == 120


def test_parser_rejects_login_or_layout_page() -> None:
    with pytest.raises(ValueError, match="marker"):
        parse_hyper_diff(_fixture(marker="ログイン"))


def test_snapshot_has_all_targets_without_inventing_availability() -> None:
    observed = datetime(2026, 9, 23, 19, 10, tzinfo=ZoneInfo("Asia/Tokyo"))
    snapshot = build_snapshot(_fixture(), observed)
    assert snapshot["target_ticker_count"] == len(JP_TICKERS) == 17
    assert snapshot["changed_target_count"] == 1
    by_ticker = {row["ticker"]: row for row in snapshot["rows"]}
    assert by_ticker["1617.T"]["hyper_status"] == "changed"
    assert by_ticker["1617.T"]["new_short_allowed"] is None
    assert by_ticker["1625.T"]["hyper_status"] == "unknown_public_diff_only"
    assert by_ticker["1625.T"]["collection_status"] == "full_list_requires_login"


def test_write_and_audit_snapshot(tmp_path: Path) -> None:
    observed = datetime(2026, 9, 23, 19, 10, tzinfo=ZoneInfo("Asia/Tokyo"))
    snapshot = build_snapshot(_fixture(), observed)
    path = write_snapshot(snapshot, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["applicable_session"] == "2026-09-24"
    audit = audit_snapshots(tmp_path, "2026-09-24")
    assert audit["observed_sessions"] == 1
    assert audit["invalid_files"] == []
    assert audit["availability_known_from_public_source"] is False
    assert audit["informational_only"] is True

