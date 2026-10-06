from __future__ import annotations

import json
from pathlib import Path

from juslag.shadow_execution import evaluate_shadow_orders


def test_evaluates_only_fully_settled_order_sheets(tmp_path: Path) -> None:
    raw = tmp_path / "raw" / "2026-10-02"
    orders = tmp_path / "manual_strategy" / "orders"
    raw.mkdir(parents=True)
    orders.mkdir(parents=True)
    (raw / "prices_tail_raw.csv").write_text(
        "ticker,date,open,close\n"
        "1301.T,2026-09-28,100,101\n"
        "1302.T,2026-09-28,,\n"
        "1301.T,2026-10-02,109,110\n",
        encoding="utf-8",
    )
    (orders / "2026-09-28-entry.json").write_text(
        json.dumps(
            {
                "strategy_id": "current-v2",
                "entry_date": "2026-09-28",
                "planned_exit_date": "2026-10-02",
                "orders": [{"ticker": "1301.T", "quantity": 100}],
            }
        ),
        encoding="utf-8",
    )
    (orders / "2026-10-02-entry.json").write_text(
        json.dumps(
            {
                "strategy_id": "current-v2",
                "entry_date": "2026-10-02",
                "planned_exit_date": "2026-10-08",
                "orders": [{"ticker": "1301.T", "quantity": 100}],
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_shadow_orders(tmp_path)

    assert len(result["batches"]) == 1
    assert result["batches"][0]["net_pnl_yen"] == 989.5
    assert result["by_strategy"]["current-v2"] == {
        "settled_batches": 1,
        "wins": 1,
        "net_pnl_yen": 989.5,
        "win_rate_pct": 100.0,
    }
