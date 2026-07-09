from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from juslag.services.store import StrategyHistoryEntry, build_strategy_history_entry

_JST = ZoneInfo("Asia/Tokyo")


def _make_entry(dedupe_key: str = "dk-1", cached_date: str = "2026-07-08", **overrides) -> StrategyHistoryEntry:
    fields = dict(
        dedupe_key=dedupe_key,
        cached_date=cached_date,
        signal_date="2026-07-07",
        exec_jp_date="2026-07-08",
        recorded_at="2026/07/08 08:00:00",
        operation_mode="production",
        tradeable=True,
        trade_block_reason=None,
        n_long=1,
        n_short=1,
        long_tickers=["1625.T"],
        long_sectors=["電機・精密"],
        short_tickers=["1630.T"],
        short_sectors=["小売"],
    )
    fields.update(overrides)
    return StrategyHistoryEntry(**fields)


def test_strategy_history_entry_defaults() -> None:
    entry = _make_entry()
    assert entry.dedupe_key == "dk-1"
    assert entry.cached_date == "2026-07-08"
    assert entry.tradeable is True
    assert entry.long_tickers == ["1625.T"]
    assert entry.regime_warning_reason == []
    assert entry.candidate_signal_stats is None


def _make_daily_signal_result(**overrides) -> dict:
    ds = {
        "signal_reference_us_date": "2026-07-07",
        "reference_date": "2026-07-07",
        "execution_target_jp_date": "2026-07-08",
        "execution_target_jp_date_source": "jpx_calendar",
        "operation_mode": "production",
        "tradeable": True,
        "trade_block_reason": None,
        "trade_signal_strength": 0.5,
        "min_signal_spread_used": 0.05,
        "execution_plan": {
            "long": [{"ticker": "1625.T", "sector": "電機・精密"}],
            "short": [{"ticker": "1630.T", "sector": "小売"}],
            "n_long": 1,
            "n_short": 1,
        },
        "data_quality": {"usable_us_tickers": 9, "usable_jp_tickers": 9},
        "freshness": {"freshness_ok": True},
        "cache_summary": {"latest_dates_aligned": True},
        "trend_regime": "uptrend",
        "vol_regime": "mid_vol",
        "rotation_regime": "mid_rotation",
        "regime_warning": False,
        "regime_warning_reason": [],
        "candidate_signal_stats": None,
        "no_trade_classification": None,
        "strategy_decision": {
            "rule_id": "rule_406",
            "rule_name_ja": "ルール406",
            "selected_strategy": "gap_ovht_oc",
            "action": "execute",
            "reason_ja": "テスト実行",
            "default_strategy": "curr_oc",
            "override_strategy": None,
            "matched_filter": None,
            "matched_override": None,
        },
        "strategy_context": {"open_gap": 0.001},
        "shadow_decisions": {},
    }
    ds.update(overrides)
    return ds


def test_build_strategy_history_entry_from_daily_signal_result() -> None:
    ds = _make_daily_signal_result()
    now_jst = datetime(2026, 7, 8, 8, 0, 0, tzinfo=_JST)

    entry = build_strategy_history_entry(ds, now_jst)

    assert entry.cached_date == "2026-07-08"
    assert entry.signal_date == "2026-07-07"
    assert entry.exec_jp_date == "2026-07-08"
    assert entry.recorded_at == "2026/07/08 08:00:00"
    assert entry.tradeable is True
    assert entry.n_long == 1
    assert entry.n_short == 1
    assert entry.long_tickers == ["1625.T"]
    assert entry.short_tickers == ["1630.T"]
    assert entry.usable_us == 9
    assert entry.usable_jp == 9
    assert entry.freshness_ok is True
    assert entry.latest_dates_aligned is True
    assert entry.strategy_rule_id == "rule_406"
    assert entry.selected_strategy == "gap_ovht_oc"
    assert entry.strategy_action == "execute"
    assert entry.strategy_reason_ja == "テスト実行"


def test_build_strategy_history_entry_dedupe_key_is_stable() -> None:
    ds = _make_daily_signal_result()
    now_jst = datetime(2026, 7, 8, 8, 0, 0, tzinfo=_JST)

    entry_a = build_strategy_history_entry(ds, now_jst)
    entry_b = build_strategy_history_entry(ds, now_jst.replace(hour=9))

    # dedupe_key only depends on signal/exec dates + tradeable + tickers, not recorded_at.
    assert entry_a.dedupe_key == entry_b.dedupe_key
    assert entry_a.recorded_at != entry_b.recorded_at


def test_build_strategy_history_entry_handles_missing_strategy_decision() -> None:
    ds = _make_daily_signal_result(strategy_decision=None, strategy_context=None, shadow_decisions=None)
    now_jst = datetime(2026, 7, 8, 8, 0, 0, tzinfo=_JST)

    entry = build_strategy_history_entry(ds, now_jst)

    assert entry.strategy_rule_id is None
    assert entry.selected_strategy is None
    assert entry.strategy_context is None
    assert entry.shadow_decisions is None
