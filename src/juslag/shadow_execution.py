from __future__ import annotations

import csv
import json
from pathlib import Path


def evaluate_shadow_orders(data_dir: Path, *, cost_bps_per_side: float = 5.0) -> dict:
    """Value generated order sheets at observed open/close without claiming real fills."""
    prices: dict[tuple[str, str], tuple[float, float]] = {}
    for path in sorted((data_dir / "raw").glob("*/prices_tail_raw.csv")):
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                try:
                    value = (float(row["open"]), float(row["close"]))
                except (TypeError, ValueError):
                    continue
                prices[(row["ticker"], row["date"])] = value

    batches = []
    for path in sorted((data_dir / "manual_strategy" / "orders").glob("*-entry.json")):
        sheet = json.loads(path.read_text(encoding="utf-8"))
        entry_date = str(sheet.get("entry_date") or "")
        exit_date = str(sheet.get("planned_exit_date") or "")
        rows = sheet.get("orders") or []
        if not entry_date or not exit_date or not rows:
            continue
        valued = []
        for order in rows:
            ticker = str(order.get("ticker") or "")
            entry = prices.get((ticker, entry_date))
            exit_price = prices.get((ticker, exit_date))
            quantity = order.get("quantity")
            if entry is None or exit_price is None or not isinstance(quantity, int):
                valued = []
                break
            open_yen = entry[0]
            close_yen = exit_price[1]
            gross = quantity * (close_yen - open_yen)
            cost = quantity * (open_yen + close_yen) * cost_bps_per_side / 10_000
            valued.append(
                {
                    "ticker": ticker,
                    "quantity": quantity,
                    "entry_open_yen": open_yen,
                    "exit_close_yen": close_yen,
                    "net_pnl_yen": round(gross - cost, 2),
                }
            )
        if not valued:
            continue
        notional = sum(row["quantity"] * row["entry_open_yen"] for row in valued)
        net = round(sum(row["net_pnl_yen"] for row in valued), 2)
        batches.append(
            {
                "strategy_id": sheet.get("strategy_id"),
                "entry_date": entry_date,
                "exit_date": exit_date,
                "notional_yen": round(notional, 2),
                "net_pnl_yen": net,
                "return_on_notional_pct": round(net / notional * 100, 4),
                "orders": valued,
                "fill_basis": "observed_open_to_close_shadow_not_real_fill",
            }
        )

    by_strategy: dict[str, dict] = {}
    for batch in batches:
        strategy_id = str(batch.get("strategy_id") or "unknown")
        summary = by_strategy.setdefault(
            strategy_id,
            {"settled_batches": 0, "wins": 0, "net_pnl_yen": 0.0},
        )
        summary["settled_batches"] += 1
        summary["wins"] += int(batch["net_pnl_yen"] > 0)
        summary["net_pnl_yen"] = round(summary["net_pnl_yen"] + batch["net_pnl_yen"], 2)
    for summary in by_strategy.values():
        count = summary["settled_batches"]
        summary["win_rate_pct"] = round(summary["wins"] / count * 100, 1) if count else None
    return {
        "schema_version": 1,
        "cost_bps_per_side": cost_bps_per_side,
        "batches": batches,
        "by_strategy": by_strategy,
        "disclaimer": "注文票の寄付→5営業日目終値によるshadow評価。実発注・実約定ではない。",
    }
