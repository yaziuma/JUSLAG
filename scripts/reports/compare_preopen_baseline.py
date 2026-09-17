#!/usr/bin/env python3
"""Compare the deployed gap rule with a research-only pre-open ablation."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from juslag.cache import PriceCache
from juslag.services.backtest import run_backtest_service
from juslag.services.settings import load_production_backtest_params
from juslag.strategies.preopen_no_gap import PreopenNoGap


def main() -> None:
    params, settings_name = load_production_backtest_params()
    if params.strategy_rule_id != "rule_406_no_flip":
        raise ValueError("This ablation requires rule_406_no_flip as the production setting")
    cache = PriceCache()
    # The experiment is pinned to the existing local cache; no new prices are fetched.
    with patch("juslag.data_loader.yf.download", return_value=pd.DataFrame()):
        current = run_backtest_service(params, cache)
        preopen = run_backtest_service(
            params.model_copy(update={"strategy_rule_id": PreopenNoGap.rule_id}),
            cache,
            research_rule=PreopenNoGap(),
        )

    def summary(bt: dict) -> dict:
        judge = bt["judge"]
        return {
            "strategy": bt["judge_strategy_name"],
            "metrics": judge.get("metrics_snapshot"),
            "judge_decision": judge.get("overall_decision"),
            "cost_breakdown": bt.get("cost_breakdown"),
        }

    result = {
        "settings_name": settings_name,
        "params": params.model_dump(),
        "current": summary(current),
        "preopen_no_gap": summary(preopen),
        "limitation": "Pre-open information only, but opening auction fills and 5bps slippage remain unverified.",
    }
    out = Path("/tmp/juslag_preopen_comparison.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
