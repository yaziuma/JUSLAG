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

    dates_by_ticker: dict[str, set[str]] = {}
    for ticker, date in prices:
        dates_by_ticker.setdefault(ticker, set()).add(date)

    batches = []
    open_batches = []
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
        if valued:
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
            continue

        tickers = [str(order.get("ticker") or "") for order in rows]
        if not tickers or any(not ticker for ticker in tickers):
            continue
        common_dates = set.intersection(
            *(dates_by_ticker.get(ticker, set()) for ticker in tickers)
        )
        mark_dates = sorted(date for date in common_dates if entry_date <= date < exit_date)
        if not mark_dates:
            continue
        valued_at = mark_dates[-1]
        marked = []
        for order in rows:
            ticker = str(order.get("ticker") or "")
            entry = prices.get((ticker, entry_date))
            mark = prices.get((ticker, valued_at))
            quantity = order.get("quantity")
            if entry is None or mark is None or not isinstance(quantity, int):
                marked = []
                break
            open_yen = entry[0]
            close_yen = mark[1]
            gross = quantity * (close_yen - open_yen)
            estimated_cost = quantity * (open_yen + close_yen) * cost_bps_per_side / 10_000
            marked.append(
                {
                    "ticker": ticker,
                    "quantity": quantity,
                    "entry_open_yen": open_yen,
                    "mark_close_yen": close_yen,
                    "unrealized_net_pnl_yen": round(gross - estimated_cost, 2),
                }
            )
        if not marked:
            continue
        notional = sum(row["quantity"] * row["entry_open_yen"] for row in marked)
        unrealized = round(sum(row["unrealized_net_pnl_yen"] for row in marked), 2)
        open_batches.append(
            {
                "strategy_id": sheet.get("strategy_id"),
                "entry_date": entry_date,
                "planned_exit_date": exit_date,
                "valued_at": valued_at,
                "notional_yen": round(notional, 2),
                "unrealized_net_pnl_yen": unrealized,
                "return_on_notional_pct": round(unrealized / notional * 100, 4),
                "orders": marked,
                "valuation_basis": "observed_entry_open_to_latest_common_close_estimated_costs_not_real_fill",
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
    open_by_strategy: dict[str, dict] = {}
    for batch in open_batches:
        strategy_id = str(batch.get("strategy_id") or "unknown")
        summary = open_by_strategy.setdefault(
            strategy_id,
            {"open_batches": 0, "unrealized_net_pnl_yen": 0.0, "latest_valued_at": None},
        )
        summary["open_batches"] += 1
        summary["unrealized_net_pnl_yen"] = round(
            summary["unrealized_net_pnl_yen"] + batch["unrealized_net_pnl_yen"], 2
        )
        valued_at = batch["valued_at"]
        if summary["latest_valued_at"] is None or valued_at > summary["latest_valued_at"]:
            summary["latest_valued_at"] = valued_at
    return {
        "schema_version": 2,
        "cost_bps_per_side": cost_bps_per_side,
        "batches": batches,
        "by_strategy": by_strategy,
        "open_batches": open_batches,
        "open_by_strategy": open_by_strategy,
        "disclaimer": "注文票を観測寄付→計画決済日終値で評価。未決済は最新共通終値による含み損益（往復コスト見積込み）。実発注・実約定ではない。",
    }
