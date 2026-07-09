"""
report_generation / report_registry のライブラリ層カバレッジ。

旧 webui `/api/report-templates` `/api/reports/generate` `/api/reports/generated-history`
の HTTP アサーションは削除し、下層のライブラリ関数を直接検証する。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from juslag.report_generation import generate_report, load_generated_history
from juslag.report_registry import templates_payload


def test_report_templates_payload_includes_known_ids() -> None:
    data = templates_payload()
    ids = {t["id"] for t in data["templates"]}
    assert {
        "direction_flip", "direction_regime", "anomaly_days",
        "position_filter", "signal_spread_history",
    }.issubset(ids)


def test_generate_report_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    report = generate_report(
        "direction_regime",
        {"from_date": "2025-01-01", "to_date": "2025-12-31", "quantile_q_from": 0.3, "quantile_q_to": 0.3},
        save_report=False,
    )
    assert report.template_id == "direction_regime"
    assert report.report_markdown
    assert report.report_path is None
    assert report.report_url is None


def test_generate_report_invalid_range_raises_value_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        generate_report(
            "direction_regime",
            {"from_date": "2025-12-31", "to_date": "2025-01-01"},
            save_report=False,
        )


def test_generate_report_with_save_returns_report_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    report = generate_report(
        "direction_flip",
        {"from_date": "2025-01-01", "to_date": "2025-12-31"},
        save_report=True,
        report_name="test_direction_flip_report",
    )
    assert report.report_url is not None
    assert report.report_url.startswith("/reports/")
    assert report.report_path is not None
    assert Path(report.report_path).exists()


def test_generate_report_appends_generated_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    generate_report(
        "anomaly_days",
        {"from_date": "2025-01-01", "to_date": "2025-12-31"},
        save_report=False,
    )
    items = load_generated_history()
    assert len(items) == 1
    assert items[0]["template_id"] == "anomaly_days"


def test_generate_report_unknown_template_raises_value_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        generate_report("does_not_exist", {}, save_report=False)
