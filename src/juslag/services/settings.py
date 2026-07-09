from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import ValidationError

from juslag.services.backtest import BacktestParams

ENV_JSON = "JUSLAG_BACKTEST_SETTINGS_JSON"
ENV_FILE = "JUSLAG_BACKTEST_SETTINGS_FILE"


def _extract_form(payload: dict) -> tuple[dict, str | None]:
    """Accept either a bare form dict or a wrapper {"name": ..., "form": {...}}.

    Returns (form, wrapper_name_or_None).
    """
    if isinstance(payload, dict) and "form" in payload and isinstance(payload["form"], dict):
        return payload["form"], payload.get("name")
    return payload, None


def _parse_params(form: dict, source_desc: str) -> BacktestParams:
    try:
        return BacktestParams(**form)
    except ValidationError as exc:
        raise ValueError(f"{source_desc} のバックテスト設定が不正です: {exc}") from exc


def load_production_backtest_params() -> tuple[BacktestParams, str]:
    """本番バックテスト設定を優先順位に従って読み込む。

    優先順位:
      1. 環境変数 JUSLAG_BACKTEST_SETTINGS_JSON (JSON文字列)
      2. 環境変数 JUSLAG_BACKTEST_SETTINGS_FILE (JSONファイルパス)

    いずれも未設定の場合は、GitHub Variable (JUSLAG_BACKTEST_SETTINGS) を
    設定するよう促すエラーを送出する。
    """
    env_json = os.environ.get(ENV_JSON)
    if env_json:
        try:
            payload = json.loads(env_json)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"環境変数 {ENV_JSON} のJSONを解析できません: {exc}"
            ) from exc
        form, wrapper_name = _extract_form(payload)
        params = _parse_params(form, f"環境変数 {ENV_JSON}")
        source_name = wrapper_name or f"env:{ENV_JSON}"
        return params, source_name

    env_file = os.environ.get(ENV_FILE)
    if env_file:
        file_path = Path(env_file)
        if not file_path.exists():
            raise ValueError(
                f"環境変数 {ENV_FILE} が指すファイルが存在しません: {file_path}"
            )
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"環境変数 {ENV_FILE} のファイルJSONを解析できません: {file_path}: {exc}"
            ) from exc
        form, wrapper_name = _extract_form(payload)
        params = _parse_params(form, f"環境変数 {ENV_FILE} ({file_path})")
        source_name = wrapper_name or f"file:{file_path}"
        return params, source_name

    raise ValueError(
        "本番バックテスト設定が見つかりません。"
        "GitHub Variable JUSLAG_BACKTEST_SETTINGS（環境変数 JUSLAG_BACKTEST_SETTINGS_JSON）"
        "または環境変数 JUSLAG_BACKTEST_SETTINGS_FILE を設定してください。"
    )
