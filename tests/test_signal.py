from __future__ import annotations

import pandas as pd
import numpy as np

import juslag.signal as signal_module
from juslag.regime import build_regime_warning
from juslag.signal import (
    ADAPTIVE_LONG_THRESHOLDS,
    ADAPTIVE_SHORT_THRESHOLDS,
    _build_candidate_signal_stats,
    _compute_execution_target_jp_date_with_source,
    append_daily_signal_log_csv,
    build_daily_signal_log_entry,
    classify_no_trade,
    compute_execution_target_jp_date,
    evaluate_daily_tradeability,
    get_todays_signal,
    resolve_thresholds,
)


def _make_signal_table(long_vals: list[float], short_vals: list[float]) -> pd.DataFrame:
    rows = []
    for i, v in enumerate(long_vals):
        rows.append({"ticker": f"L{i}", "sector": "A", "signal": v, "position": "LONG"})
    for i, v in enumerate(short_vals):
        rows.append({"ticker": f"S{i}", "sector": "B", "signal": v, "position": "SHORT"})
    if not rows:
        return pd.DataFrame(columns=["sector", "signal", "position"])
    df = pd.DataFrame(rows).set_index("ticker")
    return df.sort_values("signal", ascending=False)


_GOOD_QUALITY = {"usable_us_tickers": 11, "usable_jp_tickers": 17}
_GOOD_FRESHNESS = {"freshness_ok": True}
_GOOD_CACHE = {"latest_dates_aligned": True}
_EXEC_DATE = pd.Timestamp("2026-04-14")
_JPX_SOURCE = "jpx_calendar"


def test_tradeable_when_spread_sufficient() -> None:
    table = _make_signal_table([0.5, 0.4], [-0.3, -0.4])
    result = evaluate_daily_tradeability(
        table, _GOOD_QUALITY, _GOOD_FRESHNESS, _GOOD_CACHE,
        min_signal_spread=0.5, execution_target_jp_date=_EXEC_DATE, execution_target_jp_date_source=_JPX_SOURCE,
    )
    assert result["tradeable"] is True
    assert result["trade_block_reason"] is None
    assert result["trade_signal_strength"] > 0.5


def test_not_tradeable_when_spread_too_small() -> None:
    table = _make_signal_table([0.1, 0.05], [-0.05, -0.1])
    result = evaluate_daily_tradeability(
        table, _GOOD_QUALITY, _GOOD_FRESHNESS, _GOOD_CACHE,
        min_signal_spread=0.5, execution_target_jp_date=_EXEC_DATE, execution_target_jp_date_source=_JPX_SOURCE,
    )
    assert result["tradeable"] is False
    assert result["trade_block_reason"] == "signal_spread_too_small"


def test_not_tradeable_when_freshness_not_ok() -> None:
    table = _make_signal_table([0.5, 0.4], [-0.3, -0.4])
    bad_freshness = {"freshness_ok": False}
    result = evaluate_daily_tradeability(
        table, _GOOD_QUALITY, bad_freshness, _GOOD_CACHE,
        min_signal_spread=0.0, execution_target_jp_date=_EXEC_DATE, execution_target_jp_date_source=_JPX_SOURCE,
    )
    assert result["tradeable"] is False
    assert result["trade_block_reason"] == "freshness_not_ok"


def test_not_tradeable_when_no_execution_target_date() -> None:
    table = _make_signal_table([0.5, 0.4], [-0.3, -0.4])
    result = evaluate_daily_tradeability(
        table, _GOOD_QUALITY, _GOOD_FRESHNESS, _GOOD_CACHE,
        min_signal_spread=0.0, execution_target_jp_date=None,
    )
    assert result["tradeable"] is False
    assert result["trade_block_reason"] == "no_execution_target_date"


def test_not_tradeable_when_cache_dates_not_aligned() -> None:
    table = _make_signal_table([0.5, 0.4], [-0.3, -0.4])
    bad_cache = {"latest_dates_aligned": False}
    result = evaluate_daily_tradeability(
        table, _GOOD_QUALITY, _GOOD_FRESHNESS, bad_cache,
        min_signal_spread=0.0, execution_target_jp_date=_EXEC_DATE, execution_target_jp_date_source=_JPX_SOURCE,
    )
    assert result["tradeable"] is False
    assert result["trade_block_reason"] == "cache_dates_not_aligned"


def test_compute_execution_target_jp_date_from_calendar() -> None:
    execution_target = compute_execution_target_jp_date(pd.Timestamp("2026-04-13"))
    assert execution_target == pd.Timestamp("2026-04-14")


def test_get_todays_signal_live_without_future_jp_prices(monkeypatch) -> None:
    idx = pd.bdate_range("2026-01-01", "2026-04-13")
    us_cc = pd.DataFrame({"US1": np.linspace(0.001, 0.003, len(idx))}, index=idx)
    jp_cc = pd.DataFrame(
        {
            "JP1": np.linspace(-0.002, 0.001, len(idx)),
            "JP2": np.linspace(0.002, -0.001, len(idx)),
        },
        index=idx,
    )

    monkeypatch.setattr(signal_module, "compute_signal_at_t", lambda *args, **kwargs: np.array([0.4, -0.4]))
    result = get_todays_signal(
        us_cc=us_cc,
        jp_cc=jp_cc,
        c0=np.eye(3),
        jp_tickers_map={"JP1": "A", "JP2": "B"},
        l=20,
        k=1,
        lam=0.9,
        q=0.5,
    )

    assert result.signal_reference_us_date == pd.Timestamp("2026-04-13")
    assert result.execution_target_jp_date is not None
    assert result.execution_target_jp_date == pd.Timestamp("2026-04-14")
    assert result.execution_target_jp_date_source in {"jpx_calendar", "weekday_fallback"}


def test_compute_execution_target_jp_date_uses_fallback_when_calendar_lib_missing(monkeypatch) -> None:
    monkeypatch.setattr(signal_module, "mcal", None)
    execution_target, source = _compute_execution_target_jp_date_with_source(pd.Timestamp("2026-04-10"))
    assert execution_target == pd.Timestamp("2026-04-13")
    assert source == "weekday_fallback"


def test_tradeable_in_production_only_when_calendar_source_is_jpx() -> None:
    table = _make_signal_table([0.5, 0.4], [-0.3, -0.4])
    result = evaluate_daily_tradeability(
        table, _GOOD_QUALITY, _GOOD_FRESHNESS, _GOOD_CACHE,
        min_signal_spread=0.0, execution_target_jp_date=_EXEC_DATE, execution_target_jp_date_source="jpx_calendar", operation_mode="production",
    )
    assert result["tradeable"] is True
    assert result["trade_block_reason"] is None


def test_block_weekday_fallback_in_production_mode() -> None:
    table = _make_signal_table([0.5, 0.4], [-0.3, -0.4])
    result = evaluate_daily_tradeability(
        table, _GOOD_QUALITY, _GOOD_FRESHNESS, _GOOD_CACHE,
        min_signal_spread=0.0, execution_target_jp_date=_EXEC_DATE, execution_target_jp_date_source="weekday_fallback", operation_mode="production",
    )
    assert result["tradeable"] is False
    assert result["trade_block_reason"] == "calendar_source_untrusted"


def test_allow_weekday_fallback_in_development_mode() -> None:
    table = _make_signal_table([0.5, 0.4], [-0.3, -0.4])
    result = evaluate_daily_tradeability(
        table, _GOOD_QUALITY, _GOOD_FRESHNESS, _GOOD_CACHE,
        min_signal_spread=0.0, execution_target_jp_date=_EXEC_DATE, execution_target_jp_date_source="weekday_fallback", operation_mode="development",
    )
    assert result["tradeable"] is True
    assert result["trade_block_reason"] is None
    assert result["calendar_warning"] is True


def test_daily_signal_log_entry_keeps_required_fields(tmp_path) -> None:
    log_path = tmp_path / "daily_signal_log.csv"
    row = build_daily_signal_log_entry(
        signal_reference_us_date="2026-04-14",
        execution_target_jp_date="2026-04-15",
        execution_target_jp_date_source="jpx_calendar",
        operation_mode="production",
        trade_signal_strength=0.31,
        tradeable=True,
        trade_block_reason=None,
        min_signal_spread_used=0.3,
        freshness_ok=True,
        latest_dates_aligned=True,
        usable_us_tickers=11,
        usable_jp_tickers=17,
        long_tickers=["1621.T"],
        short_tickers=["1631.T"],
        total_return_pct=0.42,
    )
    append_daily_signal_log_csv(log_path, row)
    saved = pd.read_csv(log_path)
    assert "trade_signal_strength" in saved.columns
    assert "min_signal_spread_used" in saved.columns
    assert "total_return_pct" in saved.columns
    assert float(saved.iloc[0]["min_signal_spread_used"]) == 0.3


# ─── signal 強度条件テスト ────────────────────────────────────────────────────

def _make_raw_data(n_us: int = 2, n_jp: int = 4, length: int = 80) -> tuple:
    """quantile + 強度条件テスト用の最小データを生成する。"""
    import numpy as np
    import pandas as pd
    idx = pd.bdate_range("2024-01-01", periods=length)
    us_cc = pd.DataFrame(
        {f"US{i}": np.linspace(0.001, 0.002, length) for i in range(n_us)},
        index=idx,
    )
    rng = np.random.default_rng(42)
    jp_cc = pd.DataFrame(
        {f"JP{i}": rng.normal(0, 0.01, length) for i in range(n_jp)},
        index=idx,
    )
    c0 = np.eye(min(n_us, n_jp))
    jp_map = {f"JP{i}": f"Sector{i}" for i in range(n_jp)}
    return us_cc, jp_cc, c0, jp_map


def test_signal_strength_excludes_weak_long(monkeypatch) -> None:
    """quantile 上位だが min_long_signal 未満の銘柄は LONG にならない。"""
    us_cc, jp_cc, c0, jp_map = _make_raw_data()

    # signal を [0.20, 0.15, -0.10, -0.20] に固定
    monkeypatch.setattr(
        signal_module,
        "compute_signal_at_t",
        lambda *args, **kwargs: np.array([0.20, 0.15, -0.10, -0.20]),
    )
    result = get_todays_signal(
        us_cc, jp_cc, c0, jp_map, l=30, k=1, lam=0.9, q=0.3,
        min_long_signal=0.25,   # 0.20 も 0.15 も下回る
        max_short_signal=0.0,
    )
    # quantile 上位 = LONG 候補はあるが、強度条件で全落ち
    assert result.candidate_long_count > 0
    assert (result.table["position"] == "LONG").sum() == 0


def test_signal_strength_excludes_weak_short(monkeypatch) -> None:
    """quantile 下位だが max_short_signal より上の銘柄は SHORT にならない。"""
    us_cc, jp_cc, c0, jp_map = _make_raw_data()

    monkeypatch.setattr(
        signal_module,
        "compute_signal_at_t",
        lambda *args, **kwargs: np.array([0.20, 0.15, -0.05, -0.08]),
    )
    result = get_todays_signal(
        us_cc, jp_cc, c0, jp_map, l=30, k=1, lam=0.9, q=0.3,
        min_long_signal=0.0,
        max_short_signal=-0.10,  # -0.05 も -0.08 も上回る
    )
    assert result.candidate_short_count > 0
    assert (result.table["position"] == "SHORT").sum() == 0


def test_signal_strength_passes_both_conditions(monkeypatch) -> None:
    """quantile 条件も強度条件も満たす銘柄は正しく LONG / SHORT 採用される。"""
    us_cc, jp_cc, c0, jp_map = _make_raw_data()

    monkeypatch.setattr(
        signal_module,
        "compute_signal_at_t",
        lambda *args, **kwargs: np.array([0.30, 0.20, -0.25, -0.35]),
    )
    result = get_todays_signal(
        us_cc, jp_cc, c0, jp_map, l=30, k=1, lam=0.9, q=0.3,
        min_long_signal=0.10,
        max_short_signal=-0.10,
    )
    assert (result.table["position"] == "LONG").sum() >= 1
    assert (result.table["position"] == "SHORT").sum() >= 1


def test_signal_strength_reduces_counts(monkeypatch) -> None:
    """強度条件により採用件数が quantile 候補より少なくなる。"""
    us_cc, jp_cc, c0, jp_map = _make_raw_data()

    # LONG候補2件のうち1件だけ強度条件通過、SHORT候補2件とも通過
    monkeypatch.setattr(
        signal_module,
        "compute_signal_at_t",
        lambda *args, **kwargs: np.array([0.40, 0.05, -0.30, -0.40]),
    )
    result = get_todays_signal(
        us_cc, jp_cc, c0, jp_map, l=30, k=1, lam=0.9, q=0.5,  # q=0.5 → 2件候補
        min_long_signal=0.10,   # 0.40 は通過、0.05 は落ちる
        max_short_signal=0.0,
    )
    adopted_long = int((result.table["position"] == "LONG").sum())
    # 採用 LONG(1) < quantile 候補 LONG(2) — 強度条件で1件落ちる
    assert adopted_long < result.candidate_long_count


def test_regime_warning_downtrend_high_vol_true() -> None:
    warning, reasons, message = build_regime_warning("downtrend", "high_vol")
    assert warning is True
    assert "downtrend" in reasons
    assert "high_vol" in reasons
    assert "downtrend_high_vol" in reasons
    assert "downtrend × high_vol" in message


def test_regime_warning_uptrend_low_vol_false() -> None:
    warning, reasons, _ = build_regime_warning("uptrend", "low_vol")
    assert warning is False
    assert reasons == []


# ─── block reason 精緻化テスト ────────────────────────────────────────────────

def test_no_long_candidates_after_threshold() -> None:
    """LONG quantile 候補はあるが閾値で全落ちした場合 no_long_candidates_after_threshold。"""
    table = _make_signal_table([], [-0.3, -0.4])  # adopted_long == 0
    result = evaluate_daily_tradeability(
        table, _GOOD_QUALITY, _GOOD_FRESHNESS, _GOOD_CACHE,
        execution_target_jp_date=_EXEC_DATE, execution_target_jp_date_source=_JPX_SOURCE,
        candidate_long_count=2,   # quantile 候補あり
        candidate_short_count=2,
        adopted_long_count=0,     # 閾値で全落ち
        adopted_short_count=2,
    )
    assert result["tradeable"] is False
    assert result["trade_block_reason"] == "no_long_candidates_after_threshold"


def test_no_short_candidates_after_threshold() -> None:
    """SHORT quantile 候補はあるが閾値で全落ちした場合 no_short_candidates_after_threshold。"""
    table = _make_signal_table([0.5, 0.4], [])  # adopted_short == 0
    result = evaluate_daily_tradeability(
        table, _GOOD_QUALITY, _GOOD_FRESHNESS, _GOOD_CACHE,
        execution_target_jp_date=_EXEC_DATE, execution_target_jp_date_source=_JPX_SOURCE,
        candidate_long_count=2,
        candidate_short_count=2,  # quantile 候補あり
        adopted_long_count=2,
        adopted_short_count=0,    # 閾値で全落ち
    )
    assert result["tradeable"] is False
    assert result["trade_block_reason"] == "no_short_candidates_after_threshold"


def test_insufficient_positions_after_threshold() -> None:
    """採用件数が 0 ではないが最低件数条件を満たさない場合 insufficient_positions_after_threshold。"""
    table = _make_signal_table([0.5], [-0.3])  # LONG 1件 / SHORT 1件
    result = evaluate_daily_tradeability(
        table, _GOOD_QUALITY, _GOOD_FRESHNESS, _GOOD_CACHE,
        execution_target_jp_date=_EXEC_DATE, execution_target_jp_date_source=_JPX_SOURCE,
        candidate_long_count=2,
        candidate_short_count=2,
        adopted_long_count=1,
        adopted_short_count=1,
        min_adopted_long_count=2,  # 最低 2 件必要
        min_adopted_short_count=1,
    )
    assert result["tradeable"] is False
    assert result["trade_block_reason"] == "insufficient_positions_after_threshold"


def test_too_few_usable_tickers_still_fires_for_data_shortage() -> None:
    """データ不足による too_few_usable_tickers は候補件数と無関係に発動する。"""
    table = _make_signal_table([0.5, 0.4], [-0.3, -0.4])
    bad_quality = {"usable_us_tickers": 0, "usable_jp_tickers": 17}
    result = evaluate_daily_tradeability(
        table, bad_quality, _GOOD_FRESHNESS, _GOOD_CACHE,
        execution_target_jp_date=_EXEC_DATE, execution_target_jp_date_source=_JPX_SOURCE,
        candidate_long_count=2, candidate_short_count=2,
        adopted_long_count=2, adopted_short_count=2,
    )
    assert result["tradeable"] is False
    assert result["trade_block_reason"] == "too_few_usable_tickers"


def test_no_long_takes_priority_over_no_short() -> None:
    """LONG / SHORT 両方 0 件の場合、LONG 不足が先に検出される。"""
    table = _make_signal_table([], [])  # 両方 adopted == 0
    result = evaluate_daily_tradeability(
        table, _GOOD_QUALITY, _GOOD_FRESHNESS, _GOOD_CACHE,
        execution_target_jp_date=_EXEC_DATE, execution_target_jp_date_source=_JPX_SOURCE,
        candidate_long_count=2,
        candidate_short_count=2,
        adopted_long_count=0,
        adopted_short_count=0,
    )
    assert result["tradeable"] is False
    assert result["trade_block_reason"] == "no_long_candidates_after_threshold"


# ─── Adaptive threshold / signal stats テスト ────────────────────────────────

def test_resolve_thresholds_non_adaptive_returns_base() -> None:
    """adaptive=False のとき regime に関わらず base 値を返す。"""
    long_th, short_th = resolve_thresholds("high_vol", 0.10, -0.10, adaptive=False)
    assert long_th == 0.10
    assert short_th == -0.10


def test_resolve_thresholds_adaptive_high_vol() -> None:
    """adaptive=True かつ high_vol のとき閾値が緩まる。"""
    long_th, short_th = resolve_thresholds("high_vol", 0.10, -0.10, adaptive=True)
    assert long_th == ADAPTIVE_LONG_THRESHOLDS["high_vol"]
    assert short_th == ADAPTIVE_SHORT_THRESHOLDS["high_vol"]
    assert long_th < 0.10


def test_resolve_thresholds_adaptive_low_vol() -> None:
    """adaptive=True かつ low_vol のとき閾値が厳しくなる。"""
    long_th, short_th = resolve_thresholds("low_vol", 0.10, -0.10, adaptive=True)
    assert long_th == ADAPTIVE_LONG_THRESHOLDS["low_vol"]
    assert long_th > 0.10


def test_resolve_thresholds_adaptive_unknown_regime_falls_back() -> None:
    """adaptive=True でも未知の regime は base 値にフォールバック。"""
    long_th, short_th = resolve_thresholds("unknown_regime", 0.10, -0.10, adaptive=True)
    assert long_th == 0.10
    assert short_th == -0.10


def test_resolve_thresholds_none_regime_returns_base() -> None:
    """vol_regime=None のとき adaptive=True でも base 値を返す。"""
    long_th, short_th = resolve_thresholds(None, 0.08, -0.08, adaptive=True)
    assert long_th == 0.08
    assert short_th == -0.08


def test_candidate_signal_stats_structure() -> None:
    """_build_candidate_signal_stats が必須キーを持つ dict を返す。"""
    signal_series = pd.Series(
        [0.08, 0.06, 0.02, -0.03, -0.07],
        index=["T1", "T2", "T3", "T4", "T5"],
    )
    quantile_long = signal_series >= 0.06   # T1, T2
    quantile_short = signal_series <= -0.03  # T4, T5
    stats = _build_candidate_signal_stats(
        signal_series, quantile_long, quantile_short,
        long_threshold=0.10, short_threshold=-0.10,
        jp_tickers_map={"T1": "食品", "T2": "医薬品"},
    )
    assert "signal_max" in stats
    assert "signal_min" in stats
    assert "top_long_candidates" in stats
    assert "top_short_candidates" in stats
    assert "long_threshold_gap_max" in stats
    assert "short_threshold_gap_max" in stats
    # gap_to_threshold は負 (全員閾値未達)
    for entry in stats["top_long_candidates"]:
        assert entry["gap_to_threshold"] < 0
        assert entry["passes"] is False


def test_candidate_signal_stats_passes_when_above_threshold() -> None:
    """閾値を超える signal は passes=True になる。"""
    signal_series = pd.Series([0.15, 0.05, -0.05, -0.15], index=["A", "B", "C", "D"])
    ql = signal_series >= 0.10
    qs = signal_series <= -0.10
    stats = _build_candidate_signal_stats(signal_series, ql, qs, 0.10, -0.10, {})
    long_entries = stats["top_long_candidates"]
    assert len(long_entries) == 1
    assert long_entries[0]["ticker"] == "A"
    assert long_entries[0]["passes"] is True
    assert long_entries[0]["gap_to_threshold"] >= 0


def test_adaptive_threshold_changes_adopted_count(monkeypatch) -> None:
    """adaptive=True かつ high_vol のとき、固定閾値より採用件数が増える場合がある。"""
    us_cc, jp_cc, c0, jp_map = _make_raw_data()

    # signals: [0.08, 0.07, -0.06, -0.08] — 固定 0.10 で全落ち、adaptive 0.06 で通過
    monkeypatch.setattr(
        signal_module,
        "compute_signal_at_t",
        lambda *args, **kwargs: np.array([0.08, 0.07, -0.06, -0.08]),
    )
    result_fixed = get_todays_signal(
        us_cc, jp_cc, c0, jp_map, l=30, k=1, lam=0.9, q=0.3,
        min_long_signal=0.10, max_short_signal=-0.10,
        vol_regime="high_vol", adaptive_threshold=False,
    )
    result_ada = get_todays_signal(
        us_cc, jp_cc, c0, jp_map, l=30, k=1, lam=0.9, q=0.3,
        min_long_signal=0.10, max_short_signal=-0.10,
        vol_regime="high_vol", adaptive_threshold=True,
    )
    # 固定: 全員閾値未達
    assert result_fixed.adopted_long_count == 0
    # adaptive: high_vol threshold=0.06 → 0.08, 0.07 は通過
    assert result_ada.adopted_long_count > 0
    assert result_ada.threshold_long_used == ADAPTIVE_LONG_THRESHOLDS["high_vol"]


def test_daily_signal_result_has_threshold_fields(monkeypatch) -> None:
    """DailySignalResult に threshold_long_used / candidate_signal_stats が含まれる。"""
    us_cc, jp_cc, c0, jp_map = _make_raw_data()
    monkeypatch.setattr(
        signal_module,
        "compute_signal_at_t",
        lambda *args, **kwargs: np.array([0.30, 0.20, -0.25, -0.35]),
    )
    result = get_todays_signal(
        us_cc, jp_cc, c0, jp_map, l=30, k=1, lam=0.9, q=0.3,
        min_long_signal=0.10, max_short_signal=-0.10,
    )
    assert result.threshold_long_used == 0.10
    assert result.threshold_short_used == -0.10
    assert result.candidate_signal_stats is not None
    assert "signal_max" in result.candidate_signal_stats
    assert "top_long_candidates" in result.candidate_signal_stats


def test_trade_signal_strength_zero_when_no_positions() -> None:
    """LONG/SHORT どちらも 0 件のとき trade_signal_strength は 0.0。"""
    table = _make_signal_table([], [])
    result = evaluate_daily_tradeability(
        table, _GOOD_QUALITY, _GOOD_FRESHNESS, _GOOD_CACHE,
        execution_target_jp_date=_EXEC_DATE, execution_target_jp_date_source=_JPX_SOURCE,
        candidate_long_count=2, candidate_short_count=2,
        adopted_long_count=0, adopted_short_count=0,
    )
    assert result["trade_signal_strength"] == 0.0
    assert result["tradeable"] is False


# ---------------------------------------------------------------------------
# classify_no_trade tests
# ---------------------------------------------------------------------------

def test_classify_no_trade_returns_none_when_tradeable() -> None:
    """両サイド採用 ≥ 1 のとき None を返す。"""
    assert classify_no_trade(1, 1, -0.02, -0.02) is None
    assert classify_no_trade(3, 2, 0.01, 0.03) is None


def test_classify_no_trade_near_miss_threshold() -> None:
    """両サイド採用 0 件、gap が near_miss_margin 内 → near_miss_threshold。"""
    # gap = -0.02 > -0.03: near miss
    cls = classify_no_trade(0, 0, -0.02, -0.015)
    assert cls == "near_miss_threshold"


def test_classify_no_trade_hard_no_signal() -> None:
    """gap が near_miss_margin より遠い → hard_no_signal。"""
    cls = classify_no_trade(0, 0, -0.05, -0.08)
    assert cls == "hard_no_signal"


def test_classify_no_trade_one_side_only() -> None:
    """片側だけ採用あり → one_side_only。"""
    assert classify_no_trade(1, 0, 0.02, -0.02) == "one_side_only"
    assert classify_no_trade(0, 1, -0.02, 0.02) == "one_side_only"


def test_classify_no_trade_regime_blocked() -> None:
    """regime_warning かつ両 gap が near_miss 以内 → regime_blocked。"""
    cls = classify_no_trade(0, 0, -0.01, -0.02, regime_warning=True)
    assert cls == "regime_blocked"


def test_classify_no_trade_regime_warning_but_hard_miss() -> None:
    """regime_warning でも gap が遠ければ hard_no_signal になる。"""
    cls = classify_no_trade(0, 0, -0.08, -0.06, regime_warning=True)
    assert cls == "hard_no_signal"


def test_candidate_signal_strength_in_stats() -> None:
    """_build_candidate_signal_stats に candidate_signal_strength が含まれる。"""
    signal_series = pd.Series({"A": 0.12, "B": 0.08, "C": -0.07, "D": -0.11})
    ql_mask = signal_series >= signal_series.quantile(0.75)
    qs_mask = signal_series <= signal_series.quantile(0.25)
    stats = _build_candidate_signal_stats(signal_series, ql_mask, qs_mask, 0.10, -0.10, {})
    assert "candidate_signal_strength" in stats
    assert isinstance(stats["candidate_signal_strength"], float)
    # LONG candidate avg ≈ 0.12, SHORT ≈ -0.11, strength > 0
    assert stats["candidate_signal_strength"] > 0.0


def test_daily_signal_result_new_fields(monkeypatch) -> None:
    """get_todays_signal がすべての新フィールドを返す。"""
    us_cc, jp_cc, c0, jp_map = _make_raw_data()
    monkeypatch.setattr(
        signal_module,
        "compute_signal_at_t",
        lambda *args, **kwargs: np.array([0.30, 0.20, -0.25, -0.35]),
    )
    result = get_todays_signal(
        us_cc, jp_cc, c0, jp_map, l=30, k=1, lam=0.9, q=0.3,
        min_long_signal=0.10, max_short_signal=-0.10,
    )
    assert isinstance(result.candidate_signal_strength, float)
    assert isinstance(result.adopted_signal_strength, float)
    # All signals pass threshold (0.30, 0.20 >= 0.10; -0.25, -0.35 <= -0.10)
    assert result.adopted_signal_strength > 0.0
    # tradeable → no_trade_classification is None
    assert result.no_trade_classification is None


def test_daily_signal_result_no_trade_classified(monkeypatch) -> None:
    """閾値を超えない信号の場合、no_trade_classification が設定される。"""
    us_cc, jp_cc, c0, jp_map = _make_raw_data()
    monkeypatch.setattr(
        signal_module,
        "compute_signal_at_t",
        lambda *args, **kwargs: np.array([0.07, 0.05, -0.06, -0.04]),
    )
    result = get_todays_signal(
        us_cc, jp_cc, c0, jp_map, l=30, k=1, lam=0.9, q=0.3,
        min_long_signal=0.10, max_short_signal=-0.10,
    )
    # Signal max = 0.07, threshold = 0.10 → gap = -0.03 (near miss boundary)
    assert result.no_trade_classification is not None
    assert result.no_trade_classification in (
        "near_miss_threshold", "hard_no_signal", "one_side_only", "regime_blocked"
    )

