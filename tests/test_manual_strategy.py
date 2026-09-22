from __future__ import annotations

import copy

import pytest

from juslag.manual_strategy import (
    build_order_sheet,
    fifth_session,
    initial_state,
    record_entry,
    record_exit,
)


def _config() -> dict:
    return {
        "strategy_id": "test_manual",
        "effective_from": "2026-09-24",
        "signal_model": {"selection_quantile": 0.30},
        "portfolio": {"initial_capital_yen": 1_000_000, "deployment_fraction": 0.90},
        "execution": {
            "holding_jpx_sessions": 5,
            "entry_order_deadline_jst": "08:55",
            "exit_order_deadline_jst": "15:20",
        },
        "risk": {"maximum_drawdown_pct": -25, "require_all_17_tickers": True},
    }


def _report() -> dict:
    rows = [{"ticker": f"{code}.T", "signal": float(i)} for i, code in enumerate(range(1617, 1634))]
    return {
        "daily_signal": {
            "execution_target_jp_date": "2026-09-24",
            "signal_reference_us_date": "2026-09-18",
            "freshness": {"freshness_ok": True},
            "rows": rows,
        }
    }


def _fill(order: dict, price: float = 1000.0) -> dict:
    return {
        "ticker": order["ticker"],
        "quantity": order["quantity"],
        "fill_price": price,
        "fee_yen": 0,
        "order_id": f"order-{order['ticker']}",
        "accepted_at": "2026-09-24T08:50:00+09:00",
        "filled_at": "2026-09-24T09:00:00+09:00",
    }


def test_fifth_session_counts_entry_day_and_skips_weekend() -> None:
    assert fifth_session("2026-09-24", 5) == "2026-09-30"


def test_build_entry_selects_top_30_percent_and_sizes_with_buffer() -> None:
    state = initial_state(_config())
    prices = {f"{code}.T": 10_000.0 for code in range(1617, 1634)}
    sheet = build_order_sheet(_report(), state, _config(), prices, "2026-09-24")
    assert sheet["action"] == "ENTRY"
    assert [row["ticker"] for row in sheet["orders"]] == [
        "1633.T",
        "1632.T",
        "1631.T",
        "1630.T",
        "1629.T",
    ]
    assert sum(row["estimated_notional_yen"] for row in sheet["orders"]) <= 900_000
    assert sheet["planned_exit_date"] == "2026-09-30"
    assert len(sheet["sheet_sha256"]) == 64


def test_record_round_trip_includes_fees_and_exit_is_never_blocked_by_drawdown() -> None:
    config = _config()
    state = initial_state(config)
    prices = {f"{code}.T": 1000.0 for code in range(1617, 1634)}
    sheet = build_order_sheet(_report(), state, config, prices, "2026-09-24")
    entry_fills = [_fill(order) for order in sheet["orders"]]
    entry_fills[0]["fee_yen"] = 10
    record_entry(state, sheet, entry_fills)
    assert build_order_sheet(_report(), state, config, prices, "2026-09-25")["action"] == "HOLD"
    state["drawdown_pct"] = -30
    exit_sheet = build_order_sheet(_report(), state, config, prices, "2026-10-01")
    assert exit_sheet["action"] == "EXIT"
    assert exit_sheet["overdue"] is True
    exit_fills = [
        _fill({"ticker": row["ticker"], "quantity": row["quantity"]}, 1010) for row in entry_fills
    ]
    exit_fills[0]["fee_yen"] = 5
    record_exit(state, exit_fills)
    units = sum(row["quantity"] for row in entry_fills)
    assert state["capital_yen"] == 1_000_000 + units * 10 - 15
    assert state["open_batch"] is None


def test_entry_rejects_missing_broker_evidence_and_drawdown_blocks_new_batch() -> None:
    config = _config()
    state = initial_state(config)
    prices = {f"{code}.T": 1000.0 for code in range(1617, 1634)}
    sheet = build_order_sheet(_report(), state, config, prices, "2026-09-24")
    bad_fills = [
        {"ticker": row["ticker"], "quantity": row["quantity"], "fill_price": 1000}
        for row in sheet["orders"]
    ]
    with pytest.raises(ValueError, match="broker evidence"):
        record_entry(state, sheet, bad_fills)
    zero_fills = [_fill(order, 0) for order in sheet["orders"]]
    with pytest.raises(ValueError, match="invalid broker evidence"):
        record_entry(state, sheet, zero_fills)
    stopped = copy.deepcopy(state)
    stopped["drawdown_pct"] = -25
    with pytest.raises(ValueError, match="drawdown stop"):
        build_order_sheet(_report(), stopped, config, prices, "2026-09-24")
