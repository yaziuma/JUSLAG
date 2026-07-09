from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, Field


class StrategyHistoryEntry(BaseModel):
    dedupe_key: str
    cached_date: str
    signal_date: str | None = None
    exec_jp_date: str | None = None
    recorded_at: str
    operation_mode: str | None = None
    exec_jp_date_source: str | None = None
    tradeable: bool | None = None
    trade_block_reason: str | None = None
    trade_signal_strength: float | None = None
    min_signal_spread_used: float | None = None
    n_long: int = 0
    n_short: int = 0
    long_tickers: list[str] = Field(default_factory=list)
    long_sectors: list[str] = Field(default_factory=list)
    short_tickers: list[str] = Field(default_factory=list)
    short_sectors: list[str] = Field(default_factory=list)
    usable_us: int | None = None
    usable_jp: int | None = None
    freshness_ok: bool | None = None
    latest_dates_aligned: bool | None = None
    trend_regime: str | None = None
    vol_regime: str | None = None
    rotation_regime: str | None = None
    regime_warning: bool | None = None
    regime_warning_reason: list[str] = Field(default_factory=list)
    candidate_signal_stats: dict | None = None
    no_trade_classification: str | None = None
    strategy_rule_id: str | None = None
    strategy_rule_name_ja: str | None = None
    selected_strategy: str | None = None
    strategy_action: str | None = None
    strategy_reason_ja: str | None = None
    default_strategy: str | None = None
    override_strategy: str | None = None
    matched_filter: str | None = None
    matched_override: str | None = None
    strategy_context: dict | None = None
    shadow_decisions: dict | None = None
    order_json: dict | None = None
    raw_signal_json: str | None = None


def build_strategy_history_entry(ds: dict, now_jst: datetime) -> StrategyHistoryEntry:
    plan = ds.get("execution_plan") or {}
    long_tickers = sorted(e.get("ticker", "") for e in plan.get("long", []))
    short_tickers = sorted(e.get("ticker", "") for e in plan.get("short", []))
    dedupe_key = json.dumps({
        "signalDate": ds.get("signal_reference_us_date") or ds.get("reference_date") or None,
        "execJpDate": ds.get("execution_target_jp_date") or None,
        "tradeable": ds.get("tradeable") if ds.get("tradeable") is not None else None,
        "longTickers": long_tickers,
        "shortTickers": short_tickers,
    }, ensure_ascii=False, separators=(",", ":"))
    return StrategyHistoryEntry(
        dedupe_key=dedupe_key,
        cached_date=now_jst.date().isoformat(),
        signal_date=ds.get("signal_reference_us_date") or ds.get("reference_date") or None,
        exec_jp_date=ds.get("execution_target_jp_date") or None,
        recorded_at=now_jst.strftime("%Y/%m/%d %H:%M:%S"),
        operation_mode=ds.get("operation_mode") or "production",
        exec_jp_date_source=ds.get("execution_target_jp_date_source") or None,
        tradeable=ds.get("tradeable"),
        trade_block_reason=ds.get("trade_block_reason") or None,
        trade_signal_strength=ds.get("trade_signal_strength"),
        min_signal_spread_used=ds.get("min_signal_spread_used"),
        n_long=plan.get("n_long") or len(plan.get("long", [])),
        n_short=plan.get("n_short") or len(plan.get("short", [])),
        long_tickers=long_tickers,
        long_sectors=[e.get("sector", "") for e in plan.get("long", [])],
        short_tickers=short_tickers,
        short_sectors=[e.get("sector", "") for e in plan.get("short", [])],
        usable_us=(ds.get("data_quality") or {}).get("usable_us_tickers"),
        usable_jp=(ds.get("data_quality") or {}).get("usable_jp_tickers"),
        freshness_ok=(ds.get("freshness") or {}).get("freshness_ok"),
        latest_dates_aligned=(ds.get("cache_summary") or {}).get("latest_dates_aligned"),
        trend_regime=ds.get("trend_regime") or None,
        vol_regime=ds.get("vol_regime") or None,
        rotation_regime=ds.get("rotation_regime") or None,
        regime_warning=ds.get("regime_warning"),
        regime_warning_reason=ds.get("regime_warning_reason") or [],
        candidate_signal_stats=ds.get("candidate_signal_stats") or None,
        no_trade_classification=ds.get("no_trade_classification") or None,
        strategy_rule_id=(ds.get("strategy_decision") or {}).get("rule_id") or None,
        strategy_rule_name_ja=(ds.get("strategy_decision") or {}).get("rule_name_ja") or None,
        selected_strategy=(ds.get("strategy_decision") or {}).get("selected_strategy") or None,
        strategy_action=(ds.get("strategy_decision") or {}).get("action") or None,
        strategy_reason_ja=(ds.get("strategy_decision") or {}).get("reason_ja") or None,
        default_strategy=(ds.get("strategy_decision") or {}).get("default_strategy") or None,
        override_strategy=(ds.get("strategy_decision") or {}).get("override_strategy") or None,
        matched_filter=(ds.get("strategy_decision") or {}).get("matched_filter") or None,
        matched_override=(ds.get("strategy_decision") or {}).get("matched_override") or None,
        strategy_context=ds.get("strategy_context") or None,
        shadow_decisions=ds.get("shadow_decisions") or None,
        order_json=None,
        raw_signal_json=json.dumps(ds, ensure_ascii=False),
    )
