"""
build_order_json_payload() の canonical schema を固定するスナップショットテスト。

このテストが壊れた場合、フロントエンドの generateOrderJson() との整合性が
崩れている可能性があるため要確認。
"""
from __future__ import annotations

from juslag.services.daily_signal import build_order_json_payload


def _long_row(ticker: str = "1617.T", sector: str = "素材", lots: int = 10) -> dict:
    return {"ticker": ticker, "sector": sector, "normalized_lots": lots}


def _short_row(ticker: str = "1620.T", sector: str = "エネルギー", lots: int = 10) -> dict:
    return {"ticker": ticker, "sector": sector, "normalized_lots": lots}


def test_top_level_keys() -> None:
    payload = build_order_json_payload([_long_row()], [_short_row()])
    assert set(payload.keys()) == {"common", "orders"}


def test_long_order_keys() -> None:
    payload = build_order_json_payload([_long_row()], [])
    order = payload["orders"][0]
    assert "stock_code" in order
    assert "order_kind" in order
    assert "quantity" in order
    assert "nariyuki_condition" in order
    assert "sor_enabled" in order
    assert "note" in order
    assert "payment_limit" not in order


def test_long_order_kind_is_genbutsu_buy() -> None:
    payload = build_order_json_payload([_long_row()], [])
    assert payload["orders"][0]["order_kind"] == "genbutsu_buy"


def test_short_order_kind_is_shinyo_sell() -> None:
    payload = build_order_json_payload([], [_short_row()])
    order = payload["orders"][0]
    assert order["order_kind"] == "shinyo_sell"
    assert order.get("payment_limit") == "day"


def test_skip_produces_empty_orders() -> None:
    payload = build_order_json_payload([], [])
    assert payload["orders"] == []
