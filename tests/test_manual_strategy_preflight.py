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
        "daily_signal": {
            "execution_target_jp_date": "2026-09-24",
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
            "2026-09-24", "2026-09-24T01:00:00+00:00", "2026-09-23"
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
        as_of="2026-09-24",
        now=preflight.datetime.fromisoformat("2026-09-24T08:30:00+09:00"),
        ref="origin/main",
        config_path=config_path,
        state_path=state_path,
        output_path=output,
        status_path=status_path,
    )
    sheet = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "READY"
    assert sheet["signal_reference_us_date"] == "2026-09-21"
    assert sheet["preflight"]["source_report"] == "data/reports/2026-09-23.json"
    assert sheet["preflight"]["source_commit"] == "b" * 40


def test_preflight_blocks_after_entry_deadline(tmp_path) -> None:
    status_path = tmp_path / "status.json"
    result = preflight.run_preflight(
        as_of="2026-09-24",
        now=preflight.datetime.fromisoformat("2026-09-24T09:00:00+09:00"),
        ref="origin/main",
        config_path=Path("config/manual_strategy.yaml"),
        state_path=Path("data/manual_strategy/state.json"),
        output_path=tmp_path / "orders.json",
        status_path=status_path,
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "entry deadline has passed"
    assert not (tmp_path / "orders.json").exists()
    assert json.loads(status_path.read_text(encoding="utf-8"))["status"] == "BLOCKED"
