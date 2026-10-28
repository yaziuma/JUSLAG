import importlib.util
from pathlib import Path
import pytest
from juslag.manual_strategy import fingerprint

spec = importlib.util.spec_from_file_location(
    "manual_orders", Path("scripts/ops/manual_strategy_orders.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_independent_preflight_rejects_rehashed_tampering():
    sheet = {
        "action": "ENTRY",
        "as_of": "2026-10-02",
        "strategy_id": "test",
        "orders": [{"ticker": "1617.T", "quantity": 1}],
    }
    sheet["sheet_sha256"] = fingerprint(sheet)
    status = {
        "status": "READY",
        "action": "ENTRY",
        "as_of": sheet["as_of"],
        "strategy_id": "test",
        "sheet_sha256": sheet["sheet_sha256"],
    }
    module.verify_preflight_sheet(status, sheet)
    sheet["orders"][0]["quantity"] = 2
    sheet["sheet_sha256"] = fingerprint(
        {k: v for k, v in sheet.items() if k != "sheet_sha256"}
    )
    with pytest.raises(ValueError, match="independent preflight"):
        module.verify_preflight_sheet(status, sheet)


def test_record_entry_cli_requires_preflight_and_does_not_write_on_mismatch(
    tmp_path, monkeypatch
):
    import json
    import sys

    config = {"strategy_id": "test", "portfolio": {"initial_capital_yen": 1000000}}
    import yaml

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    state_path = tmp_path / "state.json"
    original = '{"strategy_id":"test","open_batch":null,"capital_yen":1000000}'
    state_path.write_text(original)
    sheet = {
        "action": "ENTRY",
        "as_of": "2026-10-02",
        "strategy_id": "test",
        "orders": [],
    }
    sheet["sheet_sha256"] = fingerprint(sheet)
    sheet_path = tmp_path / "sheet.json"
    sheet_path.write_text(json.dumps(sheet))
    fills_path = tmp_path / "fills.json"
    fills_path.write_text("[]")
    status_path = tmp_path / "status.json"
    status_path.write_text(
        json.dumps(
            {
                "status": "READY",
                "action": "ENTRY",
                "as_of": "2026-10-02",
                "strategy_id": "test",
                "sheet_sha256": "wrong",
            }
        )
    )
    args = [
        "orders",
        "record-entry",
        "--config",
        str(config_path),
        "--state",
        str(state_path),
        "--sheet",
        str(sheet_path),
        "--fills",
        str(fills_path),
    ]
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(SystemExit):
        module.main()
    assert state_path.read_text() == original
    monkeypatch.setattr(sys, "argv", args + ["--preflight", str(status_path)])
    with pytest.raises(ValueError, match="independent preflight"):
        module.main()
    assert state_path.read_text() == original
