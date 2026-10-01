from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from juslag.manual_strategy import initial_state, load_manual_config

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ops/manual_strategy_preflight.py"
SPEC = importlib.util.spec_from_file_location("manual_strategy_preflight", SCRIPT)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def _report(report_date: str, generated: str, signal_day: str) -> dict:
    return {
        "date": report_date,
        "generated_at_utc": generated,
        "run_provenance": {"source_commit": "c" * 40},
        "daily_signal": {
            "signal_price_mode": "adjusted",
            "execution_target_jp_date": "2026-10-02",
            "signal_reference_us_date": signal_day,
            "freshness": {"freshness_ok": True},
            "rows": [{"ticker": f"{code}.T", "signal": float(code)} for code in range(1617, 1634)],
        },
    }


def _csv() -> str:
    rows = ["ticker,date,open,close"]
    rows.extend(f"{code}.T,2026-09-18,1000,1000" for code in range(1617, 1634))
    return "\n".join(rows) + "\n"


def test_preflight_uses_newest_eligible_report_and_attests_sheet(tmp_path, monkeypatch) -> None:
    reports = {
        "data/reports/2026-09-22.json": _report(
            "2026-09-22", "2026-09-22T01:00:00+00:00", "2026-09-18"
        ),
        "data/reports/2026-09-23.json": _report(
            "2026-09-23", "2026-09-23T01:00:00+00:00", "2026-09-21"
        ),
        # Generated after the entry deadline and therefore ineligible.
        "data/reports/2026-09-24.json": _report(
            "2026-09-24", "2026-10-02T00:00:00+00:00", "2026-09-23"
        ),
    }

    def fake_git(*args: str) -> str:
        if args[0] == "ls-tree":
            return "\n".join(reports) + "\n"
        if args[0] == "rev-parse":
            return "b" * 40 + "\n"
        path = args[1].split(":", 1)[1]
        if path in reports:
            return json.dumps(reports[path])
        if path.endswith("prices_tail_raw.csv"):
            return _csv()
        raise AssertionError(args)

    monkeypatch.setattr(preflight, "_git", fake_git)
    config_path = Path("config/manual_strategy.yaml")
    config = load_manual_config(config_path)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(initial_state(config)), encoding="utf-8")
    output = tmp_path / "orders.json"
    status_path = tmp_path / "status.json"
    result = preflight.run_preflight(
        as_of="2026-10-02",
        now=preflight.datetime.fromisoformat("2026-10-02T08:30:00+09:00"),
        ref="origin/main",
        config_path=config_path,
        state_path=state_path,
        output_path=output,
        status_path=status_path,
        local_reports_dir=tmp_path / "no-local-reports",
    )
    sheet = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "READY"
    assert sheet["signal_reference_us_date"] == "2026-09-21"
    assert sheet["preflight"]["source_report"] == "data/reports/2026-09-23.json"
    assert sheet["preflight"]["source_commit"] == "b" * 40


def test_preflight_blocks_after_entry_deadline(tmp_path) -> None:
    status_path = tmp_path / "status.json"
    result = preflight.run_preflight(
        as_of="2026-10-02",
        now=preflight.datetime.fromisoformat("2026-10-02T09:00:00+09:00"),
        ref="origin/main",
        config_path=Path("config/manual_strategy.yaml"),
        state_path=Path("data/manual_strategy/state.json"),
        output_path=tmp_path / "orders.json",
        status_path=status_path,
        local_reports_dir=tmp_path / "no-local-reports",
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "entry deadline has passed"
    assert not (tmp_path / "orders.json").exists()
    assert json.loads(status_path.read_text(encoding="utf-8"))["status"] == "BLOCKED"


def test_preflight_rejects_raw_signal_prices(tmp_path, monkeypatch) -> None:
    report = _report("2026-10-02", "2026-10-01T23:00:00+00:00", "2026-10-01")
    report["daily_signal"]["signal_price_mode"] = "raw"

    def fake_git(*args: str) -> str:
        if args[0] == "ls-tree":
            return "data/reports/2026-10-02.json\n"
        if args[0] == "show":
            return json.dumps(report)
        raise AssertionError(args)

    monkeypatch.setattr(preflight, "_git", fake_git)
    result = preflight.run_preflight(
        as_of="2026-10-02",
        now=preflight.datetime.fromisoformat("2026-10-02T08:30:00+09:00"),
        ref="origin/main",
        config_path=Path("config/manual_strategy.yaml"),
        state_path=Path("data/manual_strategy/state.json"),
        output_path=tmp_path / "orders.json",
        status_path=tmp_path / "status.json",
        local_reports_dir=tmp_path / "no-local-reports",
    )

    assert result["status"] == "BLOCKED"
    assert result["reason"] == "no fresh adjusted pre-open report targets this JPX session"


def test_preflight_uses_fresh_local_report_when_github_is_delayed(
    tmp_path, monkeypatch
) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    report_path = reports_dir / "2026-09-24.json"
    report_path.write_text(
        json.dumps(
            _report("2026-09-24", "2026-09-23T21:00:00+00:00", "2026-09-23")
        ),
        encoding="utf-8",
    )

    def fake_git(*args: str) -> str:
        if args[0] == "ls-tree":
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(preflight, "_git", fake_git)
    monkeypatch.setattr(
        preflight,
        "_prices_from_local",
        lambda report_path, before_date: {
            f"{code}.T": 1000.0 for code in range(1617, 1634)
        },
    )
    config_path = Path("config/manual_strategy.yaml")
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(initial_state(load_manual_config(config_path))), encoding="utf-8"
    )
    output = tmp_path / "orders.json"
    result = preflight.run_preflight(
        as_of="2026-10-02",
        now=preflight.datetime.fromisoformat("2026-10-02T08:30:00+09:00"),
        ref="origin/main",
        config_path=config_path,
        state_path=state_path,
        output_path=output,
        status_path=tmp_path / "status.json",
        local_reports_dir=reports_dir,
    )
    sheet = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "READY"
    assert result["source_kind"] == "local"
    assert sheet["preflight"]["source_ref"] == "local"
    assert sheet["preflight"]["source_commit"] == "c" * 40
    assert len(sheet["preflight"]["source_report_sha256"]) == 64


def test_preflight_prefers_newer_lightweight_signal_snapshot(tmp_path, monkeypatch) -> None:
    reports_dir = tmp_path / "reports"
    signals_dir = tmp_path / "signals"
    reports_dir.mkdir()
    signals_dir.mkdir()
    (reports_dir / "2026-09-24.json").write_text(
        json.dumps(_report("2026-09-24", "2026-09-23T21:00:00+00:00", "2026-09-22")),
        encoding="utf-8",
    )
    snapshot = signals_dir / "2026-09-24.json"
    snapshot.write_text(
        json.dumps(_report("2026-09-24", "2026-09-23T23:48:00+00:00", "2026-09-23")),
        encoding="utf-8",
    )
    snapshot.with_name("2026-09-24.prices.csv").write_text(_csv(), encoding="utf-8")

    monkeypatch.setattr(preflight, "_git", lambda *args: "" if args[0] == "ls-tree" else None)
    monkeypatch.setattr(
        preflight,
        "_prices_from_local",
        lambda report_path, before_date: {f"{code}.T": 1000.0 for code in range(1617, 1634)},
    )
    config_path = Path("config/manual_strategy.yaml")
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(initial_state(load_manual_config(config_path))), encoding="utf-8"
    )
    output = tmp_path / "orders.json"
    result = preflight.run_preflight(
        as_of="2026-10-02",
        now=preflight.datetime.fromisoformat("2026-10-02T08:50:00+09:00"),
        ref="origin/main",
        config_path=config_path,
        state_path=state_path,
        output_path=output,
        status_path=tmp_path / "status.json",
        local_reports_dir=reports_dir,
        signal_reports_dir=signals_dir,
    )

    sheet = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "READY"
    assert result["source_kind"] == "local_signal"
    assert sheet["signal_reference_us_date"] == "2026-09-23"
    assert sheet["preflight"]["source_report"] == str(snapshot)
    assert len(sheet["preflight"]["source_report_sha256"]) == 64
    assert len(sheet["preflight"]["source_prices_sha256"]) == 64
