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


def decompose_daily_returns(current_rows: list[dict], preopen_rows: list[dict]) -> dict:
    current = pd.DataFrame(current_rows).set_index("date")
    preopen = pd.DataFrame(preopen_rows).set_index("date")
    common = current.index.intersection(preopen.index)
    current_only = current.index.difference(preopen.index)
    preopen_only = preopen.index.difference(current.index)

    def _partition(index: pd.Index, left: pd.DataFrame, right: pd.DataFrame) -> dict:
        gross_delta = float(left.reindex(index)["gross_return"].fillna(0).sum() - right.reindex(index)["gross_return"].fillna(0).sum())
        net_delta = float(left.reindex(index)["net_pre_tax_return"].fillna(0).sum() - right.reindex(index)["net_pre_tax_return"].fillna(0).sum())
        return {"days": len(index), "gross_delta_sum_bps": round(gross_delta * 10_000, 2), "net_delta_sum_bps": round(net_delta * 10_000, 2)}

    return {
        "common": _partition(common, current, preopen),
        "current_only": _partition(current_only, current, preopen),
        "preopen_only": _partition(preopen_only, current, preopen),
        "common_mean_gross_bps": {
            "current": round(float(current.loc[common, "gross_return"].mean()) * 10_000, 2),
            "preopen": round(float(preopen.loc[common, "gross_return"].mean()) * 10_000, 2),
        },
        "common_mean_net_bps": {
            "current": round(float(current.loc[common, "net_pre_tax_return"].mean()) * 10_000, 2),
            "preopen": round(float(preopen.loc[common, "net_pre_tax_return"].mean()) * 10_000, 2),
        },
        "note": "Sums of simple daily returns, not compounded performance or causal attribution.",
    }


def main() -> None:
    params, settings_name = load_production_backtest_params()
    if params.strategy_rule_id != "rule_406_no_flip":
        raise ValueError("This ablation requires rule_406_no_flip as the production setting")
    cache = PriceCache()
    # The experiment is pinned to the existing local cache; no new prices are fetched.
    with patch("juslag.data_loader.yf.download", return_value=pd.DataFrame()):
        current = run_backtest_service(params, cache, include_strategy_rule_detail=True)
        preopen = run_backtest_service(
            params.model_copy(update={"strategy_rule_id": PreopenNoGap.rule_id}),
            cache,
            research_rule=PreopenNoGap(),
            include_strategy_rule_detail=True,
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
        "daily_decomposition": decompose_daily_returns(
            current["strategy_rule_daily"], preopen["strategy_rule_daily"]
        ),
        "limitation": "Pre-open information only, but opening auction fills and 5bps slippage remain unverified.",
    }
    out = Path("/tmp/juslag_preopen_comparison.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
