from __future__ import annotations

import logging
from pathlib import Path

from juslag.logging import setup_logging


def test_setup_logging_writes_info_to_file(tmp_path: Path) -> None:
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    try:
        log_file = tmp_path / "juslag.log"
        config_path = tmp_path / "logging.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "version: 1",
                    "disable_existing_loggers: false",
                    "formatters:",
                    "  standard:",
                    "    format: '%(asctime)s | %(levelname)s | %(name)s | %(message)s'",
                    "handlers:",
                    "  file:",
                    "    class: logging.FileHandler",
                    "    level: INFO",
                    "    formatter: standard",
                    "    filename: logs/juslag.log",
                    "    encoding: utf-8",
                    "root:",
                    "  level: INFO",
                    "  handlers:",
                    "    - file",
                ]
            ),
            encoding="utf-8",
        )
        setup_logging(config_path=config_path, log_file=log_file)

        logger = logging.getLogger("juslag.test")
        logger.info("info message for file")

        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "info message for file" in content
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
        for handler in original_handlers:
            root.addHandler(handler)
        root.setLevel(original_level)
