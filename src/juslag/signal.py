from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from juslag.data_loader import build_joint_cc
from juslag.model import compute_signal_at_t

try:
    import pandas_market_calendars as mcal
except ImportError:  # pragma: no cover - optional dependency fallback
    mcal = None


@dataclass
class DailySignalResult:
    table: pd.DataFrame
    signal_reference_us_date: pd.Timestamp
    execution_target_jp_date: pd.Timestamp | None
    execution_target_jp_date_source: str | None = None
    candidate_long_count: int = 0
    candidate_short_count: int = 0
    adopted_long_count: int = 0
    adopted_short_count: int = 0
    excluded_long: list[dict[str, object]] | None = None
    excluded_short: list[dict[str, object]] | None = None
    threshold_long_used: float = 0.0
    threshold_short_used: float = 0.0
    candidate_signal_stats: dict[str, object] | None = None
    candidate_signal_strength: float = 0.0
    adopted_signal_strength: float = 0.0
    threshold_gap_long_max: float | None = None
    threshold_gap_short_max: float | None = None
    no_trade_classification: str | None = None
    selected_strategy: str = "curr_oc"


# ---------------------------------------------------------------------------
# Regime-adaptive threshold tables
# ---------------------------------------------------------------------------

ADAPTIVE_LONG_THRESHOLDS: dict[str, float] = {
    "low_vol":  0.12,
    "mid_vol":  0.10,
    "high_vol": 0.06,
}

ADAPTIVE_SHORT_THRESHOLDS: dict[str, float] = {
    "low_vol":  -0.12,
    "mid_vol":  -0.10,
    "high_vol": -0.06,
}


def resolve_thresholds(
    vol_regime: str | None,
    base_long: float,
    base_short: float,
    adaptive: bool = False,
) -> tuple[float, float]:
    """Return (long_threshold, short_threshold) for the given regime.

    When adaptive=True and vol_regime is known, returns regime-specific thresholds.
    Otherwise returns the base values unchanged.
    """
    if not adaptive or vol_regime is None:
        return base_long, base_short
    long_th = ADAPTIVE_LONG_THRESHOLDS.get(vol_regime, base_long)
    short_th = ADAPTIVE_SHORT_THRESHOLDS.get(vol_regime, base_short)
    return long_th, short_th


def _build_candidate_signal_stats(
    signal_series: pd.Series,
    quantile_long_mask: pd.Series,
    quantile_short_mask: pd.Series,
    long_threshold: float,
    short_threshold: float,
    jp_tickers_map: dict[str, str],
) -> dict[str, object]:
    """Compute per-bucket signal statistics for UI and logging."""
    all_signals = signal_series.sort_values(ascending=False)
    long_candidates = signal_series[quantile_long_mask].sort_values(ascending=False)
    short_candidates = signal_series[quantile_short_mask].sort_values(ascending=True)

    def _ticker_entries(s: pd.Series, threshold: float, side: str) -> list[dict]:
        entries = []
        for ticker, sig in s.head(5).items():
            gap = float(sig) - threshold if side == "long" else threshold - float(sig)
            entries.append({
                "ticker": str(ticker),
                "sector": jp_tickers_map.get(str(ticker), str(ticker)),
                "signal": round(float(sig), 6),
                "threshold": threshold,
                "gap_to_threshold": round(gap, 6),
                "passes": gap >= 0,
            })
        return entries

    long_gap_max = round(float(long_candidates.max()) - long_threshold, 6) if not long_candidates.empty else None
    short_gap_max = round(short_threshold - float(short_candidates.min()), 6) if not short_candidates.empty else None
    long_mean = float(long_candidates.mean()) if not long_candidates.empty else 0.0
    short_mean = float(short_candidates.mean()) if not short_candidates.empty else 0.0

    return {
        "signal_max": round(float(all_signals.max()), 6) if not all_signals.empty else None,
        "signal_min": round(float(all_signals.min()), 6) if not all_signals.empty else None,
        "signal_p25": round(float(all_signals.quantile(0.25)), 6) if not all_signals.empty else None,
        "signal_p50": round(float(all_signals.quantile(0.50)), 6) if not all_signals.empty else None,
        "signal_p75": round(float(all_signals.quantile(0.75)), 6) if not all_signals.empty else None,
        "long_threshold": long_threshold,
        "short_threshold": short_threshold,
        "top_long_candidates": _ticker_entries(long_candidates, long_threshold, "long"),
        "top_short_candidates": _ticker_entries(short_candidates, short_threshold, "short"),
        "long_threshold_gap_max": long_gap_max,
        "short_threshold_gap_max": short_gap_max,
        "candidate_signal_strength": round(long_mean - short_mean, 6),
    }


def classify_no_trade(
    adopted_long: int,
    adopted_short: int,
    threshold_gap_long_max: float | None,
    threshold_gap_short_max: float | None,
    regime_warning: bool = False,
    near_miss_margin: float = 0.03,
) -> str | None:
    """Classify why a day has no trade.

    Returns None if the day is tradeable (both sides adopted >= 1).
    Otherwise returns one of:
      'near_miss_threshold'  — signals are close to threshold but just miss
      'one_side_only'        — one side passes threshold, other doesn't
      'regime_blocked'       — regime warning active AND signals are near-miss
      'hard_no_signal'       — signals are far from threshold on both sides
    """
    if adopted_long >= 1 and adopted_short >= 1:
        return None

    long_ok = adopted_long >= 1
    short_ok = adopted_short >= 1
    if long_ok != short_ok:
        return "one_side_only"

    # Both adopted == 0 from here
    long_gap = threshold_gap_long_max if threshold_gap_long_max is not None else float("-inf")
    short_gap = threshold_gap_short_max if threshold_gap_short_max is not None else float("-inf")

    # regime_blocked: regime_warning AND both sides are near-miss (strong signal held back by risk)
    if regime_warning and long_gap > -near_miss_margin and short_gap > -near_miss_margin:
        return "regime_blocked"

    # near_miss_threshold: at least one side is close to threshold
    if long_gap > -near_miss_margin or short_gap > -near_miss_margin:
        return "near_miss_threshold"

    return "hard_no_signal"


DAILY_SIGNAL_LOG_FIELDS: tuple[str, ...] = (
    "created_at",
    "signal_reference_us_date",
    "execution_target_jp_date",
    "execution_target_jp_date_source",
    "operation_mode",
    "trade_signal_strength",
    "tradeable",
    "trade_block_reason",
    "min_signal_spread_used",
    "min_long_signal_used",
    "max_short_signal_used",
    "min_adopted_long_count_used",
    "min_adopted_short_count_used",
    "candidate_long_count",
    "candidate_short_count",
    "adopted_long_count",
    "adopted_short_count",
    "freshness_ok",
    "latest_dates_aligned",
    "usable_us_tickers",
    "usable_jp_tickers",
    "n_long",
    "n_short",
    "long_tickers",
    "short_tickers",
    "long_contribution_pct",
    "short_contribution_pct",
    "total_return_pct",
    "details_json",
    "trend_regime",
    "vol_regime",
    "rotation_regime",
    "regime_warning",
    "regime_warning_reason",
    "candidate_signal_strength",
    "adopted_signal_strength",
    "threshold_gap_long_max",
    "threshold_gap_short_max",
    "no_trade_classification",
)


def _compute_execution_target_jp_date_with_source(
    signal_reference_us_date: pd.Timestamp,
) -> tuple[pd.Timestamp | None, str | None]:
    """Compute the next JP business day from a reference US signal date.

    Uses JPX trading calendar when `pandas_market_calendars` is available.
    Falls back to weekday-only logic when the dependency is unavailable.
    """
    if pd.isna(signal_reference_us_date):
        return None, None

    reference_date = pd.Timestamp(signal_reference_us_date).normalize()
    start = reference_date + pd.Timedelta(days=1)

    if mcal is not None:
        calendar = mcal.get_calendar("JPX")
        for horizon_days in (14, 60, 366):
            end = reference_date + pd.Timedelta(days=horizon_days)
            schedule = calendar.schedule(start_date=start, end_date=end)
            if not schedule.empty:
                return pd.Timestamp(schedule.index[0]).tz_localize(None), "jpx_calendar"
        return None, "jpx_calendar_unavailable"

    candidate = start
    for _ in range(14):
        if candidate.weekday() < 5:
            return candidate, "weekday_fallback"
        candidate += pd.Timedelta(days=1)
    return None, "weekday_fallback_unavailable"


def compute_execution_target_jp_date(signal_reference_us_date: pd.Timestamp) -> pd.Timestamp | None:
    execution_target_jp_date, _ = _compute_execution_target_jp_date_with_source(signal_reference_us_date)
    return execution_target_jp_date


def evaluate_daily_tradeability(
    signal_table: pd.DataFrame,
    data_quality: dict[str, object],
    freshness: dict[str, object],
    cache_summary: dict[str, object],
    min_signal_spread: float = 0.0,
    execution_target_jp_date: pd.Timestamp | None = None,
    execution_target_jp_date_source: str | None = None,
    operation_mode: str = "production",
    candidate_long_count: int = 0,
    candidate_short_count: int = 0,
    adopted_long_count: int = 0,
    adopted_short_count: int = 0,
    min_adopted_long_count: int = 1,
    min_adopted_short_count: int = 1,
) -> dict[str, object]:
    """Evaluate whether today's signal is strong enough to trade.

    Returns a dict with:
        trade_signal_strength: float (mean LONG signal - mean SHORT signal)
        tradeable: bool
        trade_block_reason: str | None

    Block reason priority:
        freshness_not_ok
        cache_dates_not_aligned
        too_few_usable_tickers          (usable ticker count < 1)
        no_execution_target_date
        calendar_source_untrusted
        no_long_candidates_after_threshold   (candidate > 0 but adopted == 0)
        no_short_candidates_after_threshold  (candidate > 0 but adopted == 0)
        too_few_usable_tickers          (quantile yielded no candidates at all)
        insufficient_positions_after_threshold (adopted < min but > 0)
        signal_spread_too_small
    """
    has_position_col = not signal_table.empty and "position" in signal_table.columns
    long_s = signal_table.loc[signal_table["position"] == "LONG", "signal"] if has_position_col else pd.Series(dtype=float)
    short_s = signal_table.loc[signal_table["position"] == "SHORT", "signal"] if has_position_col else pd.Series(dtype=float)

    if not long_s.empty and not short_s.empty:
        trade_signal_strength = float(long_s.mean() - short_s.mean())
    else:
        trade_signal_strength = 0.0

    block_reason: str | None = None
    if not bool(freshness.get("freshness_ok", False)):
        block_reason = "freshness_not_ok"
    elif not bool(cache_summary.get("latest_dates_aligned", True)):
        block_reason = "cache_dates_not_aligned"
    elif int(data_quality.get("usable_us_tickers") or 0) < 1 or int(data_quality.get("usable_jp_tickers") or 0) < 1:
        block_reason = "too_few_usable_tickers"
    elif execution_target_jp_date is None:
        block_reason = "no_execution_target_date"
    elif operation_mode == "production" and execution_target_jp_date_source != "jpx_calendar":
        block_reason = "calendar_source_untrusted"
    elif candidate_long_count > 0 and adopted_long_count == 0:
        block_reason = "no_long_candidates_after_threshold"
    elif candidate_short_count > 0 and adopted_short_count == 0:
        block_reason = "no_short_candidates_after_threshold"
    elif long_s.empty or short_s.empty:
        # quantile itself yielded no candidates (edge case: data too sparse)
        block_reason = "too_few_usable_tickers"
    elif (candidate_long_count > 0 or candidate_short_count > 0) and (
        adopted_long_count < min_adopted_long_count or adopted_short_count < min_adopted_short_count
    ):
        # Only evaluate min_adopted when caller explicitly passed candidate counts
        block_reason = "insufficient_positions_after_threshold"
    elif trade_signal_strength < min_signal_spread:
        block_reason = "signal_spread_too_small"

    calendar_warning = operation_mode == "development" and execution_target_jp_date_source == "weekday_fallback"
    return {
        "trade_signal_strength": round(trade_signal_strength, 6),
        "tradeable": block_reason is None,
        "trade_block_reason": block_reason,
        "calendar_warning": calendar_warning,
    }


def compute_tradeability_signal_stats(
    signal_table: pd.DataFrame,
    long_threshold: float,
    short_threshold: float,
    jp_tickers_map: dict[str, str] | None = None,
) -> dict[str, object]:
    """Compute signal distribution stats for the tradeability response.

    Returns top excluded LONG candidates and bottom excluded SHORT candidates
    with their distance to threshold — used for UI 見送り explanation.
    """
    if signal_table.empty or "signal" not in signal_table.columns:
        return {}
    jp_map = jp_tickers_map or {}
    quantile_long_mask = signal_table.get("position_before_threshold") == "candidate_long" if "position_before_threshold" in signal_table.columns else signal_table["signal"] >= signal_table["signal"].quantile(0.7)
    quantile_short_mask = signal_table.get("position_before_threshold") == "candidate_short" if "position_before_threshold" in signal_table.columns else signal_table["signal"] <= signal_table["signal"].quantile(0.3)

    long_cands = signal_table.loc[quantile_long_mask, "signal"].sort_values(ascending=False)
    short_cands = signal_table.loc[quantile_short_mask, "signal"].sort_values(ascending=True)

    def _entries(s: pd.Series, threshold: float, side: str) -> list[dict]:
        entries = []
        for ticker, sig in s.head(5).items():
            gap = float(sig) - threshold if side == "long" else threshold - float(sig)
            entries.append({
                "ticker": str(ticker),
                "sector": jp_map.get(str(ticker), str(ticker)),
                "signal": round(float(sig), 6),
                "threshold": threshold,
                "gap_to_threshold": round(gap, 6),
                "passes": gap >= 0,
            })
        return entries

    all_s = signal_table["signal"]
    return {
        "signal_max": round(float(all_s.max()), 6) if not all_s.empty else None,
        "signal_min": round(float(all_s.min()), 6) if not all_s.empty else None,
        "signal_p50": round(float(all_s.median()), 6) if not all_s.empty else None,
        "long_threshold": long_threshold,
        "short_threshold": short_threshold,
        "top_long_candidates": _entries(long_cands, long_threshold, "long"),
        "top_short_candidates": _entries(short_cands, short_threshold, "short"),
        "long_threshold_gap_max": round(float(long_cands.max()) - long_threshold, 6) if not long_cands.empty else None,
        "short_threshold_gap_max": round(short_threshold - float(short_cands.min()), 6) if not short_cands.empty else None,
    }


def append_daily_signal_log_csv(path: str | Path, row: dict[str, object]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    normalized = {field: row.get(field) for field in DAILY_SIGNAL_LOG_FIELDS}
    needs_header = not output.exists()
    with output.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(DAILY_SIGNAL_LOG_FIELDS))
        if needs_header:
            writer.writeheader()
        writer.writerow(normalized)


def build_daily_signal_log_entry(
    *,
    signal_reference_us_date: str | None,
    execution_target_jp_date: str | None,
    execution_target_jp_date_source: str | None,
    operation_mode: str,
    trade_signal_strength: float | None,
    tradeable: bool | None,
    trade_block_reason: str | None,
    min_signal_spread_used: float,
    min_long_signal_used: float = 0.0,
    max_short_signal_used: float = 0.0,
    min_adopted_long_count_used: int = 1,
    min_adopted_short_count_used: int = 1,
    candidate_long_count: int = 0,
    candidate_short_count: int = 0,
    adopted_long_count: int | None = None,
    adopted_short_count: int | None = None,
    freshness_ok: bool | None = None,
    latest_dates_aligned: bool | None,
    usable_us_tickers: int | None,
    usable_jp_tickers: int | None,
    long_tickers: list[str],
    short_tickers: list[str],
    long_contribution_pct: float | None = None,
    short_contribution_pct: float | None = None,
    total_return_pct: float | None = None,
    details: list[dict[str, object]] | None = None,
    trend_regime: str | None = None,
    vol_regime: str | None = None,
    rotation_regime: str | None = None,
    regime_warning: bool | None = None,
    regime_warning_reason: list[str] | None = None,
    candidate_signal_strength: float | None = None,
    adopted_signal_strength: float | None = None,
    threshold_gap_long_max: float | None = None,
    threshold_gap_short_max: float | None = None,
    no_trade_classification: str | None = None,
) -> dict[str, object]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "signal_reference_us_date": signal_reference_us_date,
        "execution_target_jp_date": execution_target_jp_date,
        "execution_target_jp_date_source": execution_target_jp_date_source,
        "operation_mode": operation_mode,
        "trade_signal_strength": trade_signal_strength,
        "tradeable": tradeable,
        "trade_block_reason": trade_block_reason,
        "min_signal_spread_used": min_signal_spread_used,
        "min_long_signal_used": min_long_signal_used,
        "max_short_signal_used": max_short_signal_used,
        "min_adopted_long_count_used": min_adopted_long_count_used,
        "min_adopted_short_count_used": min_adopted_short_count_used,
        "candidate_long_count": candidate_long_count,
        "candidate_short_count": candidate_short_count,
        "adopted_long_count": adopted_long_count if adopted_long_count is not None else len(long_tickers),
        "adopted_short_count": adopted_short_count if adopted_short_count is not None else len(short_tickers),
        "freshness_ok": freshness_ok,
        "latest_dates_aligned": latest_dates_aligned,
        "usable_us_tickers": usable_us_tickers,
        "usable_jp_tickers": usable_jp_tickers,
        "n_long": len(long_tickers),
        "n_short": len(short_tickers),
        "long_tickers": "|".join(long_tickers),
        "short_tickers": "|".join(short_tickers),
        "long_contribution_pct": long_contribution_pct,
        "short_contribution_pct": short_contribution_pct,
        "total_return_pct": total_return_pct,
        "details_json": json.dumps(details or [], ensure_ascii=False),
        "trend_regime": trend_regime,
        "vol_regime": vol_regime,
        "rotation_regime": rotation_regime,
        "regime_warning": regime_warning,
        "regime_warning_reason": json.dumps(regime_warning_reason or [], ensure_ascii=False),
        "candidate_signal_strength": candidate_signal_strength,
        "adopted_signal_strength": adopted_signal_strength,
        "threshold_gap_long_max": threshold_gap_long_max,
        "threshold_gap_short_max": threshold_gap_short_max,
        "no_trade_classification": no_trade_classification,
    }


def generate_signals(us_cc: pd.DataFrame, jp_cc: pd.DataFrame, c0: np.ndarray, l: int = 60, k: int = 3, lam: float = 0.9) -> pd.DataFrame:
    """Generate historical JP signals indexed by signal date."""
    us_tickers = us_cc.columns.tolist()
    jp_tickers = jp_cc.columns.tolist()
    n_u = len(us_tickers)
    joint_cc, _ = build_joint_cc(us_cc, jp_cc)

    signals: dict[pd.Timestamp, dict[str, float]] = {}
    dates = joint_cc.index
    for i in range(l, len(dates)):
        t = dates[i]
        window_dates = dates[i - l : i]
        r_win = joint_cc.loc[window_dates].values
        mu_w = r_win.mean(axis=0)
        sig_w = r_win.std(axis=0) + 1e-10
        z_win = (r_win - mu_w) / sig_w

        r_us_t = joint_cc.loc[t, us_tickers].values
        z_us_t = (r_us_t - mu_w[:n_u]) / sig_w[:n_u]
        sig_vec = compute_signal_at_t(z_win, z_us_t, c0, n_u=n_u, k=k, lam=lam)
        signals[t] = dict(zip(jp_tickers, sig_vec))

    signal_df = pd.DataFrame(signals).T
    signal_df.index.name = "date"
    return signal_df


def get_todays_signal(us_cc: pd.DataFrame, jp_cc: pd.DataFrame, c0: np.ndarray, jp_tickers_map: dict[str, str], l: int = 60, k: int = 3, lam: float = 0.9, q: float = 0.3, min_long_signal: float = 0.0, max_short_signal: float = 0.0, vol_regime: str | None = None, adaptive_threshold: bool = False, regime_warning: bool = False) -> DailySignalResult:
    """Return latest signal table, reference US market date, and JP execution target date.

    Returns:
        DailySignalResult:
            table: DataFrame columns: sector, signal, position (index=ticker)
            signal_reference_us_date: signal calculation date (latest aligned day)
            execution_target_jp_date: first JP trading day after signal_reference_us_date, or None
    """
    us_tickers = us_cc.columns.tolist()
    jp_tickers = jp_cc.columns.tolist()
    n_u = len(us_tickers)

    joint_cc, _ = build_joint_cc(us_cc, jp_cc)
    dates = joint_cc.index
    if len(dates) < l + 1:
        return DailySignalResult(
            table=pd.DataFrame(columns=["sector", "signal", "position"]),
            signal_reference_us_date=pd.NaT,
            execution_target_jp_date=None,
        )

    window_dates = dates[-(l + 1) : -1]
    today = dates[-1]
    r_win = joint_cc.loc[window_dates].values
    mu_w = r_win.mean(axis=0)
    sig_w = r_win.std(axis=0) + 1e-10
    z_win = (r_win - mu_w) / sig_w

    r_us_t = joint_cc.loc[today, us_tickers].values
    z_us_t = (r_us_t - mu_w[:n_u]) / sig_w[:n_u]

    sig_vec = compute_signal_at_t(z_win, z_us_t, c0, n_u=n_u, k=k, lam=lam)
    result = pd.DataFrame({
        "ticker": jp_tickers,
        "sector": [jp_tickers_map.get(t, t) for t in jp_tickers],
        "signal": sig_vec,
    }).set_index("ticker")

    eff_long_th, eff_short_th = resolve_thresholds(vol_regime, min_long_signal, max_short_signal, adaptive_threshold)

    lo = result["signal"].quantile(q)
    hi = result["signal"].quantile(1.0 - q)
    quantile_long_mask = result["signal"] >= hi
    quantile_short_mask = result["signal"] <= lo
    long_mask = quantile_long_mask & (result["signal"] >= eff_long_th)
    short_mask = quantile_short_mask & (result["signal"] <= eff_short_th)
    candidate_long_count = int(quantile_long_mask.sum())
    candidate_short_count = int(quantile_short_mask.sum())
    adopted_long_count = int(long_mask.sum())
    adopted_short_count = int(short_mask.sum())
    result["position"] = "neutral"
    result.loc[long_mask, "position"] = "LONG"
    result.loc[short_mask, "position"] = "SHORT"

    excluded_long_mask = quantile_long_mask & ~long_mask
    excluded_short_mask = quantile_short_mask & ~short_mask
    excluded_long = [
        {"ticker": t, "sector": str(result.loc[t, "sector"]), "signal": round(float(result.loc[t, "signal"]), 6)}
        for t in result.index[excluded_long_mask]
    ]
    excluded_short = [
        {"ticker": t, "sector": str(result.loc[t, "sector"]), "signal": round(float(result.loc[t, "signal"]), 6)}
        for t in result.index[excluded_short_mask]
    ]

    stats = _build_candidate_signal_stats(
        result["signal"], quantile_long_mask, quantile_short_mask,
        eff_long_th, eff_short_th, jp_tickers_map,
    )

    adopted_long_sig = result.loc[long_mask, "signal"]
    adopted_short_sig = result.loc[short_mask, "signal"]
    adopted_signal_strength = round(float(adopted_long_sig.mean() - adopted_short_sig.mean()), 6) if not adopted_long_sig.empty and not adopted_short_sig.empty else 0.0
    cand_strength = float(stats.get("candidate_signal_strength") or 0.0)
    tg_long = stats.get("long_threshold_gap_max")
    tg_short = stats.get("short_threshold_gap_max")
    no_trade = classify_no_trade(
        adopted_long_count, adopted_short_count,
        tg_long, tg_short,
        regime_warning=regime_warning,
    )

    execution_target_jp_date, execution_target_jp_date_source = _compute_execution_target_jp_date_with_source(today)

    return DailySignalResult(
        table=result.sort_values("signal", ascending=False),
        signal_reference_us_date=today,
        execution_target_jp_date=execution_target_jp_date,
        execution_target_jp_date_source=execution_target_jp_date_source,
        candidate_long_count=candidate_long_count,
        candidate_short_count=candidate_short_count,
        adopted_long_count=adopted_long_count,
        adopted_short_count=adopted_short_count,
        excluded_long=excluded_long,
        excluded_short=excluded_short,
        threshold_long_used=eff_long_th,
        threshold_short_used=eff_short_th,
        candidate_signal_stats=stats,
        candidate_signal_strength=cand_strength,
        adopted_signal_strength=adopted_signal_strength,
        threshold_gap_long_max=tg_long,
        threshold_gap_short_max=tg_short,
        no_trade_classification=no_trade,
    )


# GAP_FILTER_THRESHOLD は build_period_quant_output.py の gap_aligned_0.005 / long_gap_0.005 と同一
GAP_FILTER_THRESHOLD = 0.005


def apply_strategy_decision(
    result: DailySignalResult,
    selected_strategy: str,
    overnight_gap: "pd.Series | None" = None,
    gap_threshold: float = GAP_FILTER_THRESHOLD,
) -> DailySignalResult:
    """StrategyDecision の selected_strategy に基づきポジションを書き換えて返す。

    overnight_gap: pd.Series (index=ticker) = jp_open / jp_close.shift(1) - 1 の最新行。
    gap_threshold: GapOvht / LGap フィルターで使う閾値（デフォルト 0.005）。

    selected_strategy の対応:
        curr_oc       — 変更なし（現行OC）
        gap_ovht_oc   — LONG側 gap>thr を除外、SHORT側 gap<-thr を除外
        lgap_oc       — LONG側 gap>thr を除外（SHORT は変更なし）
        long_flip_oc  — LONG → SHORT に反転（SHORT はそのまま SHORT）
        short_only_oc — LONG → neutral
        skip          — 全ポジション → neutral
    """
    if selected_strategy == "curr_oc":
        return DailySignalResult(
            **{**result.__dict__, "selected_strategy": "curr_oc"}
        )

    table = result.table.copy()
    gap = overnight_gap

    if selected_strategy == "skip":
        table["position"] = "neutral"
        adopted_long = 0
        adopted_short = 0

    elif selected_strategy == "long_flip_oc":
        table.loc[table["position"] == "LONG", "position"] = "SHORT"
        adopted_long = 0
        adopted_short = int((table["position"] == "SHORT").sum())

    elif selected_strategy == "short_only_oc":
        table.loc[table["position"] == "LONG", "position"] = "neutral"
        adopted_long = 0
        adopted_short = int((table["position"] == "SHORT").sum())

    elif selected_strategy == "gap_ovht_oc" and gap is not None:
        for ticker in table.index:
            if ticker not in gap.index:
                continue
            g = float(gap[ticker])
            pos = table.loc[ticker, "position"]
            if pos == "LONG" and g > gap_threshold:
                table.loc[ticker, "position"] = "neutral"
            elif pos == "SHORT" and g < -gap_threshold:
                table.loc[ticker, "position"] = "neutral"
        adopted_long = int((table["position"] == "LONG").sum())
        adopted_short = int((table["position"] == "SHORT").sum())

    elif selected_strategy == "lgap_oc" and gap is not None:
        for ticker in table.index:
            if ticker not in gap.index:
                continue
            g = float(gap[ticker])
            if table.loc[ticker, "position"] == "LONG" and g > gap_threshold:
                table.loc[ticker, "position"] = "neutral"
        adopted_long = int((table["position"] == "LONG").sum())
        adopted_short = int((table["position"] == "SHORT").sum())

    else:
        # overnight_gap が None の gap 戦略 や未知の strategy → curr_oc にフォールバック
        return DailySignalResult(
            **{**result.__dict__, "selected_strategy": selected_strategy}
        )

    no_trade = classify_no_trade(
        adopted_long, adopted_short,
        result.threshold_gap_long_max, result.threshold_gap_short_max,
        regime_warning=False,
    )

    return DailySignalResult(
        table=table,
        signal_reference_us_date=result.signal_reference_us_date,
        execution_target_jp_date=result.execution_target_jp_date,
        execution_target_jp_date_source=result.execution_target_jp_date_source,
        candidate_long_count=result.candidate_long_count,
        candidate_short_count=result.candidate_short_count,
        adopted_long_count=adopted_long,
        adopted_short_count=adopted_short,
        excluded_long=result.excluded_long,
        excluded_short=result.excluded_short,
        threshold_long_used=result.threshold_long_used,
        threshold_short_used=result.threshold_short_used,
        candidate_signal_stats=result.candidate_signal_stats,
        candidate_signal_strength=result.candidate_signal_strength,
        adopted_signal_strength=result.adopted_signal_strength,
        threshold_gap_long_max=result.threshold_gap_long_max,
        threshold_gap_short_max=result.threshold_gap_short_max,
        no_trade_classification=no_trade,
        selected_strategy=selected_strategy,
    )
