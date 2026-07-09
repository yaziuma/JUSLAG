from __future__ import annotations

import logging
import logging.config
from pathlib import Path

import yaml


DEFAULT_LOGGING_YAML = Path(__file__).resolve().parents[2] / "config" / "logging.yaml"


def setup_logging(config_path: str | Path | None = None, log_file: str | Path | None = None) -> None:
    """Configure application logging from YAML."""
    yaml_path = Path(config_path) if config_path is not None else DEFAULT_LOGGING_YAML
    with yaml_path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    if not isinstance(loaded, dict):
        raise ValueError(f"Logging config must be a mapping: {yaml_path}")
    logging_config: dict[str, object] = loaded

    handlers = logging_config.get("handlers")
    if isinstance(handlers, dict) and isinstance(handlers.get("file"), dict):
        file_handler = handlers["file"]
        if log_file is not None:
            file_path = Path(log_file)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler["filename"] = str(file_path)
        else:
            configured_filename = file_handler.get("filename")
            if isinstance(configured_filename, str):
                Path(configured_filename).parent.mkdir(parents=True, exist_ok=True)

    logging.config.dictConfig(logging_config)
