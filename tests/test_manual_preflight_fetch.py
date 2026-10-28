from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ops/manual_strategy_preflight.py"
SPEC = importlib.util.spec_from_file_location("manual_preflight_fetch", SCRIPT)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)

ERRORS = [
    subprocess.CalledProcessError(128, ["git", "fetch"], output="mock-private-output",
                                  stderr="mock-private-error"),
    subprocess.TimeoutExpired(["git", "fetch"], 30, output="mock-private-output",
                             stderr="mock-private-error"),
    FileNotFoundError("mock-private-error"),
]


@pytest.fixture(autouse=True)
def isolated_dependencies(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected external or order-processing call")

    monkeypatch.setattr(preflight.subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(preflight, "_git", forbidden)
    monkeypatch.setattr(preflight, "build_order_sheet", forbidden)
    monkeypatch.setattr(preflight, "build_execution_intent", forbidden)
    monkeypatch.setattr(preflight, "load_manual_config", lambda path: {
        "strategy_id": "mock-strategy",
        "execution_intent": {"release_time_jst": "08:42"},
        "execution": {"entry_order_deadline_jst": "08:55"},
    })


def install_fetch_mock(monkeypatch, error=None):
    calls = []

    def fetch(command, **kwargs):
        assert command == ["git", "fetch", "origin", "main"]
        assert kwargs == {
            "check": True, "timeout": 30, "capture_output": True, "text": True,
        }
        calls.append(command)
        if error is not None:
            raise error
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(preflight.subprocess, "run", fetch)
    return calls


@pytest.mark.parametrize("error,kind", list(zip(ERRORS, ["nonzero_exit", "timeout", "unavailable"], strict=True)))
@pytest.mark.parametrize("existing_files", [False, True])
def test_fetch_failure_records_blocked_without_processing_orders(
    tmp_path, monkeypatch, error, kind, existing_files,
):
    calls = install_fetch_mock(monkeypatch, error)

    def forbidden(*args, **kwargs):
        raise AssertionError("must stop before date checks or candidate selection")

    monkeypatch.setattr(preflight, "_is_jpx_session", forbidden)
    monkeypatch.setattr(preflight, "_candidate_reports", forbidden)
    monkeypatch.setattr(preflight, "_candidate_local_reports", forbidden)
    output, intent, status = (tmp_path / name for name in ("orders.json", "intent.json", "status.json"))
    if existing_files:
        output.write_text("existing-order-fixture")
        intent.write_text("existing-intent-fixture")
        status.write_text('{"status":"READY","execution_intent":"old-fixture"}')
    result = preflight.run_preflight(
        as_of="2026-10-14", now=preflight.datetime.fromisoformat("2026-10-14T08:42:00+09:00"),
        ref="origin/main", config_path=tmp_path / "config.yaml", state_path=tmp_path / "state.json",
        output_path=output, status_path=status, intent_output_path=intent,
        local_reports_dir=tmp_path / "reports", signal_reports_dir=tmp_path / "signals",
        fetch_source=True,
    )
    assert json.loads(status.read_text()) == result
    assert result["status"] == "BLOCKED"
    assert result["reason"] == result["reason_code"] == "source_fetch_failed"
    assert result["fetch_error"] == kind
    assert result["as_of"] == "2026-10-14"
    assert result["checked_at_jst"] == "2026-10-14T08:42:00+09:00"
    assert "execution_intent" not in result
    assert "mock-private" not in status.read_text()
    assert len(calls) == 1
    if kind == "nonzero_exit":
        assert result["fetch_returncode"] == 128
    else:
        assert "fetch_returncode" not in result
    if existing_files:
        assert output.read_text() == "existing-order-fixture"
        assert intent.read_text() == "existing-intent-fixture"
    else:
        assert not output.exists() and not intent.exists()


@pytest.mark.parametrize("error", ERRORS)
def test_cli_fetch_failure_persists_status_and_exits_one(tmp_path, monkeypatch, capsys, error):
    install_fetch_mock(monkeypatch, error)
    status, output, intent = (tmp_path / name for name in ("status.json", "orders.json", "intent.json"))
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--fetch", "--as-of", "2026-10-14",
        "--now-jst", "2026-10-14T08:42:00+09:00", "--config", str(tmp_path / "config.yaml"),
        "--state", str(tmp_path / "state.json"), "--status", str(status),
        "--output", str(output), "--intent-output", str(intent),
        "--signal-reports-dir", str(tmp_path / "signals")])
    with pytest.raises(SystemExit) as exc:
        preflight.main()
    assert exc.value.code == 1
    printed = capsys.readouterr()
    assert json.loads(printed.out) == json.loads(status.read_text())
    assert "mock-private" not in printed.out + printed.err
    assert not output.exists() and not intent.exists()


@pytest.mark.parametrize("fetch_source", [False, True])
def test_successful_or_disabled_fetch_keeps_existing_candidate_checks(tmp_path, monkeypatch, fetch_source):
    calls = install_fetch_mock(monkeypatch)
    monkeypatch.setattr(preflight, "_is_jpx_session", lambda day: True)
    monkeypatch.setattr(preflight, "_candidate_reports", lambda *args: [])
    monkeypatch.setattr(preflight, "_candidate_local_reports", lambda *args: [])
    result = preflight.run_preflight(
        as_of="2026-10-14", now=preflight.datetime.fromisoformat("2026-10-14T08:42:00+09:00"),
        ref="origin/main", config_path=tmp_path / "config.yaml", state_path=tmp_path / "state.json",
        output_path=tmp_path / "orders.json", status_path=tmp_path / "status.json",
        intent_output_path=tmp_path / "intent.json", local_reports_dir=tmp_path / "reports",
        fetch_source=fetch_source,
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "no fresh adjusted pre-open report matches the manual signal model"
    assert "reason_code" not in result
    assert len(calls) == int(fetch_source)
