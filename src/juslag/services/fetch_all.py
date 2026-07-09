from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from juslag.cache import PriceCache
from juslag.config import JP_TICKERS, US_TICKERS
from juslag.data_loader import fetch_data


def run_script_capture(script: Path, cwd: Path, args: list[str] | None = None) -> tuple[str, int]:
    cmd = [sys.executable, str(script)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return (result.stdout + "\n" + result.stderr).strip(), result.returncode


def run_fetch_all(
    start: str,
    end: str,
    price_modes: list[str],
    include_factors: bool,
    include_actions: bool,
    project_root: Path,
    cache: PriceCache,
    on_step: Callable[[str, dict], None] | None = None,
) -> dict:
    step_names = [f"price_{mode}" for mode in price_modes]
    if include_factors:
        step_names.append("factors")
    if include_actions:
        step_names.append("actions")
    step_names.append("data_status_refresh")
    steps: dict[str, dict] = {
        name: {"name": name, "status": "queued", "updated_at": time.time()} for name in step_names
    }

    def run_step(name: str, fn) -> None:
        step = steps[name]
        step["status"] = "running"
        step["updated_at"] = time.time()
        try:
            fn(step)
            step["status"] = "ok"
            step["updated_at"] = time.time()
        except Exception as exc:  # noqa: BLE001
            step["status"] = "error"
            step["updated_at"] = time.time()
            step["error"] = str(exc)
        if on_step is not None:
            on_step(name, step)

    def price_fetch(mode: str) -> None:
        fetch_data(list(US_TICKERS.keys()), list(JP_TICKERS.keys()), start, end, price_mode=mode)

    def run_external_step(step: dict, script: Path, script_cwd: Path) -> None:
        log, code = run_script_capture(script, script_cwd)
        step["log"] = log
        if code != 0:
            raise RuntimeError(log)

    for mode in price_modes:
        run_step(f"price_{mode}", lambda step, m=mode: price_fetch(m))

    if include_factors:
        script = project_root / "scripts" / "data" / "fetch_factor_data.py"
        run_step("factors", lambda step: run_external_step(step, script, project_root))
    if include_actions:
        script = project_root / "scripts" / "data" / "fetch_corporate_actions.py"
        run_step("actions", lambda step: run_external_step(step, script, project_root))

    run_step(
        "data_status_refresh",
        lambda step: cache.summary(list(US_TICKERS.keys()), list(JP_TICKERS.keys()), price_mode="raw"),
    )
    ok = all(v["status"] == "ok" for v in steps.values())
    error_summary = [f"{k}: {v.get('error')}" for k, v in steps.items() if v.get("status") == "error"]
    return {
        "status": "ok" if ok else "partial_error",
        "steps": steps,
        "error_summary": error_summary,
    }
