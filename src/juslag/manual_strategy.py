from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
import pandas_market_calendars as mcal
import yaml

from juslag.config import JP_TICKERS, JP_TRADING_UNITS


def load_manual_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def initial_state(config: dict[str, Any]) -> dict[str, Any]:
    capital = int(config["portfolio"]["initial_capital_yen"])
    return {
        "schema_version": 1,
        "strategy_id": config["strategy_id"],
        "capital_yen": capital,
        "high_watermark_yen": capital,
        "drawdown_pct": 0.0,
        "open_batch": None,
        "history": [],
    }


def fifth_session(entry_date: str, holding_sessions: int = 5) -> str:
    start = pd.Timestamp(entry_date)
    schedule = mcal.get_calendar("JPX").schedule(start, start + pd.Timedelta(days=20))
    dates = [d.date().isoformat() for d in schedule.index if d >= start]
    if len(dates) < holding_sessions:
        raise ValueError("insufficient JPX calendar sessions")
    return dates[holding_sessions - 1]


def latest_prices(path: Path, before_date: str) -> dict[str, float]:
    frame = pd.read_csv(path)
    frame = frame[(frame["ticker"].isin(JP_TICKERS)) & (frame["date"] < before_date)]
    latest = frame.sort_values("date").groupby("ticker").tail(1)
    return {str(row.ticker): float(row.close) for row in latest.itertuples()}


def fingerprint(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def build_order_sheet(
    report: dict[str, Any],
    state: dict[str, Any],
    config: dict[str, Any],
    prices: dict[str, float],
    as_of: str,
) -> dict[str, Any]:
    if state["strategy_id"] != config["strategy_id"]:
        raise ValueError("state strategy_id mismatch")
    open_batch = state.get("open_batch")
    if open_batch:
        if as_of < open_batch["exit_date"]:
            return {
                "strategy_id": config["strategy_id"],
                "as_of": as_of,
                "action": "HOLD",
                "orders": [],
            }
        orders = [
            {
                "stock_code": position["ticker"].removesuffix(".T"),
                "order_kind": "genbutsu_sell",
                "quantity": position["quantity"],
                "condition": "引成",
            }
            for position in open_batch["positions"]
        ]
        return {
            "strategy_id": config["strategy_id"],
            "as_of": as_of,
            "action": "EXIT",
            "planned_exit_date": open_batch["exit_date"],
            "overdue": as_of > open_batch["exit_date"],
            "orders": orders,
        }

    if float(state["drawdown_pct"]) <= float(config["risk"]["maximum_drawdown_pct"]):
        raise ValueError("maximum drawdown stop is active")

    daily = report["daily_signal"]
    target = str(daily["execution_target_jp_date"])
    if target != as_of or as_of < config["effective_from"]:
        raise ValueError("report execution target does not match as_of")
    if not daily["freshness"]["freshness_ok"]:
        raise ValueError("price inputs are stale")
    rows = daily["rows"]
    if config["risk"]["require_all_17_tickers"] and len(rows) != len(JP_TICKERS):
        raise ValueError("signal panel does not contain all 17 tickers")
    signal = pd.Series({row["ticker"]: float(row["signal"]) for row in rows})
    threshold = float(signal.quantile(1 - config["signal_model"]["selection_quantile"]))
    selected = signal[signal >= threshold].sort_values(ascending=False)
    deployable = int(
        float(state["capital_yen"]) * float(config["portfolio"]["deployment_fraction"])
    )
    budget = deployable / len(selected)
    orders = []
    for ticker, value in selected.items():
        price = prices.get(ticker)
        if price is None or price <= 0:
            raise ValueError(f"missing sizing price for {ticker}")
        lot = JP_TRADING_UNITS[ticker]
        quantity = math.floor(budget / (price * lot)) * lot
        if quantity < lot:
            raise ValueError(f"capital too small for {ticker}")
        orders.append(
            {
                "stock_code": ticker.removesuffix(".T"),
                "ticker": ticker,
                "sector": JP_TICKERS[ticker],
                "signal": value,
                "quantity": quantity,
                "sizing_price_yen": price,
                "estimated_notional_yen": round(quantity * price),
                "order_kind": "genbutsu_buy",
                "condition": "寄成",
            }
        )
    sheet = {
        "schema_version": 1,
        "strategy_id": config["strategy_id"],
        "as_of": as_of,
        "action": "ENTRY",
        "signal_reference_us_date": daily["signal_reference_us_date"],
        "entry_date": as_of,
        "planned_exit_date": fifth_session(as_of, config["execution"]["holding_jpx_sessions"]),
        "capital_yen": state["capital_yen"],
        "deployment_fraction": config["portfolio"]["deployment_fraction"],
        "entry_order_deadline_jst": config["execution"]["entry_order_deadline_jst"],
        "exit_order_deadline_jst": config["execution"]["exit_order_deadline_jst"],
        "orders": orders,
        "manual_checks": [
            "SBI画面で銘柄・数量・寄成を照合",
            "全注文の受付番号と受付時刻を保存",
            "約定後に実数量・価格を台帳へ記録",
            "planned_exit_dateの引成注文を当日手動発注",
        ],
    }
    sheet["sheet_sha256"] = fingerprint(sheet)
    return sheet


def record_entry(
    state: dict[str, Any], sheet: dict[str, Any], fills: list[dict[str, Any]]
) -> dict[str, Any]:
    if sheet["action"] != "ENTRY" or state.get("open_batch"):
        raise ValueError("entry cannot be recorded")
    preflight = sheet.get("preflight", {})
    if preflight.get("status") != "READY" or not preflight.get("source_commit"):
        raise ValueError("entry sheet lacks a READY preflight attestation")
    planned = {row["ticker"]: int(row["quantity"]) for row in sheet["orders"]}
    if len({row["ticker"] for row in fills}) != len(fills):
        raise ValueError("duplicate entry fill ticker")
    required = {"ticker", "quantity", "fill_price", "order_id", "accepted_at", "filled_at"}
    if any(not required.issubset(row) for row in fills):
        raise ValueError("entry fills lack broker evidence fields")
    if any(float(row["fill_price"]) <= 0 or not str(row["order_id"]).strip() for row in fills):
        raise ValueError("entry fills contain invalid broker evidence")
    actual = {row["ticker"]: int(row["quantity"]) for row in fills}
    if actual != planned:
        raise ValueError("fills do not exactly match planned quantities")
    fees = sum(float(row.get("fee_yen", 0)) for row in fills)
    cost = sum(int(row["quantity"]) * float(row["fill_price"]) for row in fills) + fees
    if cost > float(state["capital_yen"]):
        raise ValueError("entry fills exceed available capital")
    state["open_batch"] = {
        "entry_date": sheet["entry_date"],
        "exit_date": sheet["planned_exit_date"],
        "sheet_sha256": sheet["sheet_sha256"],
        "positions": fills,
    }
    return state


def record_exit(state: dict[str, Any], fills: list[dict[str, Any]]) -> dict[str, Any]:
    batch = state.get("open_batch")
    if not batch:
        raise ValueError("no open batch")
    required = {"ticker", "quantity", "fill_price", "order_id", "accepted_at", "filled_at"}
    if any(not required.issubset(row) for row in fills):
        raise ValueError("exit fills lack broker evidence fields")
    if any(float(row["fill_price"]) <= 0 or not str(row["order_id"]).strip() for row in fills):
        raise ValueError("exit fills contain invalid broker evidence")
    if len({row["ticker"] for row in fills}) != len(fills):
        raise ValueError("duplicate exit fill ticker")
    entries = {row["ticker"]: row for row in batch["positions"]}
    exits = {row["ticker"]: row for row in fills}
    if set(entries) != set(exits):
        raise ValueError("exit tickers do not match open positions")
    fees = sum(float(row.get("fee_yen", 0)) for row in batch["positions"] + fills)
    pnl = -fees
    for ticker, entry in entries.items():
        exit_fill = exits[ticker]
        if int(exit_fill["quantity"]) != int(entry["quantity"]):
            raise ValueError("exit quantity mismatch")
        pnl += int(entry["quantity"]) * (
            float(exit_fill["fill_price"]) - float(entry["fill_price"])
        )
    state["capital_yen"] = round(float(state["capital_yen"]) + pnl)
    state["high_watermark_yen"] = max(
        float(state["high_watermark_yen"]), float(state["capital_yen"])
    )
    state["drawdown_pct"] = round((state["capital_yen"] / state["high_watermark_yen"] - 1) * 100, 4)
    state["history"].append(
        {
            "entry": batch,
            "exit_fills": fills,
            "fees_yen": round(fees),
            "pnl_yen": round(pnl),
        }
    )
    state["open_batch"] = None
    return state
