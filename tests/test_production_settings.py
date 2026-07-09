from __future__ import annotations

import json
from pathlib import Path

import pytest

from juslag.services.settings import (
    ENV_FILE,
    ENV_JSON,
    load_production_backtest_params,
)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_JSON, raising=False)
    monkeypatch.delenv(ENV_FILE, raising=False)


def test_env_json_wins_over_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    file_path = tmp_path / "settings_file.json"
    file_path.write_text(json.dumps({"form": {"window_l": 40}}), encoding="utf-8")
    monkeypatch.setenv(ENV_FILE, str(file_path))

    monkeypatch.setenv(
        ENV_JSON,
        json.dumps({"name": "env-wrapper", "form": {"window_l": 20}}),
    )

    params, source_name = load_production_backtest_params()
    assert params.window_l == 20
    assert source_name == "env-wrapper"


def test_env_json_bare_form_uses_env_source_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(ENV_JSON, json.dumps({"window_l": 30}))

    params, source_name = load_production_backtest_params()
    assert params.window_l == 30
    assert source_name == f"env:{ENV_JSON}"


def test_env_file_is_used_when_json_env_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    file_path = tmp_path / "settings_file.json"
    file_path.write_text(
        json.dumps({"name": "file-wrapper", "form": {"window_l": 45}}), encoding="utf-8"
    )
    monkeypatch.setenv(ENV_FILE, str(file_path))

    params, source_name = load_production_backtest_params()
    assert params.window_l == 45
    assert source_name == "file-wrapper"


def test_env_file_missing_path_raises_value_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(ENV_FILE, str(tmp_path / "does_not_exist.json"))
    with pytest.raises(ValueError):
        load_production_backtest_params()


def test_missing_everything_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    with pytest.raises(ValueError):
        load_production_backtest_params()


def test_invalid_form_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(ENV_JSON, json.dumps({"window_l": 999999}))
    with pytest.raises(ValueError):
        load_production_backtest_params()
