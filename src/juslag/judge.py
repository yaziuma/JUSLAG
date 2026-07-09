from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class JudgeInput:
    strategy_name: str
    performance_sets: dict[str, list[dict[str, Any]]]
    cost_breakdown: dict[str, float]
    data_quality: dict[str, Any]
    freshness: dict[str, Any]
    cache_summary: dict[str, Any]


@dataclass(frozen=True)
class JudgeThresholdConfig:
    min_after_tax_ar_pct: float = 3.0
    min_after_tax_rr: float = 0.30
    max_after_tax_mdd_pct: float = -25.0
    max_cost_drag_pct: float = 3.0
    max_tax_drag_pct: float = 5.0
    min_usable_us_tickers: int = 8
    min_usable_jp_tickers: int = 12
    require_strict_fill_policy: bool = True
    require_freshness_ok: bool = True
    require_cache_isolation: bool = True


def extract_metric_row(
    performance_sets: dict[str, list[dict[str, object]]],
    key: str,
) -> dict[str, object]:
    rows = performance_sets.get(key)
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"Missing performance set row: {key}")
    row = rows[0]
    if not isinstance(row, dict):
        raise ValueError(f"Invalid performance set row type for {key}: {type(row)!r}")
    return row


def _as_float(value: object, name: str) -> float:
    if value is None:
        raise ValueError(f"Missing metric value: {name}")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid metric value for {name}: {value!r}") from exc


def _build_metrics_snapshot(payload: JudgeInput) -> dict[str, float]:
    gross_row = extract_metric_row(payload.performance_sets, "gross")
    net_pre_tax_row = extract_metric_row(payload.performance_sets, "net_pre_tax")
    net_after_tax_row = extract_metric_row(payload.performance_sets, "net_after_tax")

    gross_ar_pct = _as_float(gross_row.get("AR(%)"), "gross.AR(%)")
    net_pre_tax_ar_pct = _as_float(net_pre_tax_row.get("AR(%)"), "net_pre_tax.AR(%)")
    net_after_tax_ar_pct = _as_float(net_after_tax_row.get("AR(%)"), "net_after_tax.AR(%)")

    snapshot: dict[str, float] = {
        "gross_ar_pct": gross_ar_pct,
        "gross_risk_pct": _as_float(gross_row.get("Risk(%)"), "gross.Risk(%)"),
        "gross_rr": _as_float(gross_row.get("R/R"), "gross.R/R"),
        "gross_mdd_pct": _as_float(gross_row.get("MDD(%)"), "gross.MDD(%)"),
        "net_pre_tax_ar_pct": net_pre_tax_ar_pct,
        "net_pre_tax_rr": _as_float(net_pre_tax_row.get("R/R"), "net_pre_tax.R/R"),
        "net_pre_tax_mdd_pct": _as_float(net_pre_tax_row.get("MDD(%)"), "net_pre_tax.MDD(%)"),
        "net_after_tax_ar_pct": net_after_tax_ar_pct,
        "net_after_tax_risk_pct": _as_float(net_after_tax_row.get("Risk(%)"), "net_after_tax.Risk(%)"),
        "net_after_tax_rr": _as_float(net_after_tax_row.get("R/R"), "net_after_tax.R/R"),
        "net_after_tax_mdd_pct": _as_float(net_after_tax_row.get("MDD(%)"), "net_after_tax.MDD(%)"),
        "n_days": _as_float(net_after_tax_row.get("N_days"), "net_after_tax.N_days"),
    }

    snapshot["cost_drag_pct"] = gross_ar_pct - net_pre_tax_ar_pct
    snapshot["tax_drag_pct"] = net_pre_tax_ar_pct - net_after_tax_ar_pct
    return snapshot


def _add_reason(reasons: list[dict[str, str]], code: str, severity: str, message: str) -> None:
    reasons.append({"code": code, "severity": severity, "message": message})


def _finalize_category(points: int, maximum: int) -> tuple[int, str]:
    if maximum <= 0:
        return 0, "warn"
    ratio = points / maximum
    if ratio >= 0.8:
        return points, "pass"
    if ratio >= 0.5:
        return points, "hold"
    return points, "warn"


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _score_profitability(
    ar: float,
    rr: float,
    cfg: JudgeThresholdConfig,
) -> tuple[int, int, int]:
    """Return (total_score, ar_score, rr_penalty).  Max = 30."""
    if ar >= 10.0:
        ar_score = 30
    elif ar >= 8.0:
        ar_score = 28
    elif ar >= 6.0:
        ar_score = 24
    elif ar >= 4.0:
        ar_score = 20
    elif ar >= 3.0:
        ar_score = 18
    elif ar >= 1.0:
        ar_score = 12
    elif ar >= 0.0:
        ar_score = 8
    else:
        ar_score = 0

    rr_penalty = 0
    if rr < 0.0:
        rr_penalty = 8
    elif rr < cfg.min_after_tax_rr * 0.5:
        rr_penalty = 6
    elif rr < cfg.min_after_tax_rr:
        rr_penalty = 4

    total = max(0, ar_score - rr_penalty)
    return total, ar_score, rr_penalty


def _score_stability(
    mdd: float,
    rr: float,
    cfg: JudgeThresholdConfig,
) -> tuple[int, int, int]:
    """Return (total_score, mdd_score, rr_penalty).  Max = 25."""
    if mdd >= -10.0:
        mdd_score = 25
    elif mdd >= -12.5:
        mdd_score = 22
    elif mdd >= -15.0:
        mdd_score = 20
    elif mdd >= -17.5:
        mdd_score = 18
    elif mdd >= -20.0:
        mdd_score = 16
    elif mdd >= -22.5:
        mdd_score = 13
    elif mdd >= -25.0:
        mdd_score = 10
    else:
        mdd_score = 0

    min_rr = cfg.min_after_tax_rr
    rr_penalty = 0
    if rr < min_rr * 0.5:
        rr_penalty = 3
    elif rr < min_rr:
        rr_penalty = 2

    total = max(0, mdd_score - rr_penalty)
    return total, mdd_score, rr_penalty


def _score_cost_resilience(
    cost_drag: float,
    tax_drag: float,
) -> tuple[int, int, int]:
    """Return (total_score, market_cost_score, tax_score).  Max = 20."""
    if cost_drag < 1.0:
        market_cost_score = 12
    elif cost_drag < 2.0:
        market_cost_score = 9
    elif cost_drag < 3.0:
        market_cost_score = 6
    elif cost_drag < 4.0:
        market_cost_score = 3
    else:
        market_cost_score = 0

    if tax_drag < 1.0:
        tax_score = 8
    elif tax_drag < 2.5:
        tax_score = 6
    elif tax_drag < 5.0:
        tax_score = 3
    else:
        tax_score = 0

    total = market_cost_score + tax_score
    return total, market_cost_score, tax_score


def judge_backtest(
    payload: JudgeInput,
    thresholds: JudgeThresholdConfig | None = None,
) -> dict[str, object]:
    cfg = thresholds or JudgeThresholdConfig()
    metrics = _build_metrics_snapshot(payload)

    reasons: list[dict[str, str]] = []
    actions: list[str] = []
    reject_codes: list[str] = []

    freshness_ok = bool(payload.freshness.get("freshness_ok", False))
    cache_isolation = bool(payload.data_quality.get("cache_isolated_by_price_mode", False))
    fill_policy = str(payload.data_quality.get("fill_policy", ""))
    latest_dates_aligned = bool(payload.cache_summary.get("latest_dates_aligned", False))
    daily_signal_ready = bool(payload.cache_summary.get("daily_signal_ready", False))

    stale_tickers = payload.freshness.get("stale_tickers") or []
    missing_tickers = payload.freshness.get("missing_tickers") or []

    usable_us = int(payload.data_quality.get("usable_us_tickers") or 0)
    usable_jp = int(payload.data_quality.get("usable_jp_tickers") or 0)

    # ------------------------------------------------------------------
    # Reject conditions (hard gates)
    # ------------------------------------------------------------------
    if cfg.require_freshness_ok and not freshness_ok:
        reject_codes.append("DATA_FRESHNESS_FAILED")
        _add_reason(reasons, "DATA_FRESHNESS_FAILED", "reject", "データ新鮮度チェックに失敗しています。")
        actions.append("データ更新を実行し stale/missing ティッカーを解消してください。")

    if cfg.require_cache_isolation and not cache_isolation:
        reject_codes.append("CACHE_ISOLATION_FAILED")
        _add_reason(reasons, "CACHE_ISOLATION_FAILED", "reject", "価格モード別のキャッシュ分離が崩れています。")
        actions.append("raw/adjusted を分離したキャッシュ再構築を実施してください。")

    if usable_us < cfg.min_usable_us_tickers:
        reject_codes.append("TOO_FEW_US_TICKERS")
        _add_reason(reasons, "TOO_FEW_US_TICKERS", "reject", "US 側の有効ティッカー数が最低基準を下回っています。")
        actions.append("US ティッカーの欠損を確認し、取得対象または期間を見直してください。")

    if usable_jp < cfg.min_usable_jp_tickers:
        reject_codes.append("TOO_FEW_JP_TICKERS")
        _add_reason(reasons, "TOO_FEW_JP_TICKERS", "reject", "JP 側の有効ティッカー数が最低基準を下回っています。")
        actions.append("JP ティッカーの欠損を確認し、取得対象または期間を見直してください。")

    if metrics["net_after_tax_ar_pct"] < -5.0:
        reject_codes.append("SEVERELY_NEGATIVE_AFTER_TAX_RETURN")
        _add_reason(reasons, "SEVERELY_NEGATIVE_AFTER_TAX_RETURN", "reject", "税引後年率収益が深刻なマイナスです。")
        actions.append("戦略ロジックを再検証し、パラメータ探索をやり直してください。")

    # ------------------------------------------------------------------
    # Profitability (30 pts)
    # ------------------------------------------------------------------
    ar = metrics["net_after_tax_ar_pct"]
    rr = metrics["net_after_tax_rr"]

    profitability, _ar_score, _prof_rr_penalty = _score_profitability(ar, rr, cfg)

    if ar < cfg.min_after_tax_ar_pct:
        _add_reason(reasons, "LOW_AFTER_TAX_RETURN", "warn", "税引後年率収益が最低基準を下回っています。")
        actions.append("シグナル閾値(quantile_q)を調整し、上位下位選別を強化してください。")
    if rr < cfg.min_after_tax_rr:
        _add_reason(reasons, "LOW_AFTER_TAX_RR", "warn", "税引後の R/R が最低基準を下回っています。")
        actions.append("ボラティリティ抑制のために window_l や lambda_reg を再調整してください。")

    # ------------------------------------------------------------------
    # Stability (25 pts)
    # ------------------------------------------------------------------
    mdd = metrics["net_after_tax_mdd_pct"]
    stability, _mdd_score, _stab_rr_penalty = _score_stability(mdd, rr, cfg)

    if mdd < cfg.max_after_tax_mdd_pct:
        _add_reason(reasons, "DEEP_AFTER_TAX_DRAWDOWN", "warn", "税引後ドローダウンが深く安定性が不足しています。")
        actions.append("損失が大きい局面のエクスポージャ制御を追加してください。")

    # ------------------------------------------------------------------
    # Cost resilience (20 pts = market_cost 12 + tax 8)
    # ------------------------------------------------------------------
    cost_drag = metrics["cost_drag_pct"]
    tax_drag = metrics["tax_drag_pct"]
    cost_resilience, _market_cost_score, _tax_score = _score_cost_resilience(cost_drag, tax_drag)

    # HIGH_COST_DRAG: score is already penalised via market_cost_score = 0 when cost_drag >= 4.0,
    # or reduced at lower thresholds.  Warn reason fires when drag exceeds configured max.
    if cost_drag > cfg.max_cost_drag_pct:
        _add_reason(reasons, "HIGH_COST_DRAG", "warn", "Gross から Net Pre-Tax への低下幅が大きく、コスト耐性が弱いです。")
        actions.append("commission/slippage/borrow 前提を見直してください。")

    # HIGH_TAX_DRAG: score already penalised via tax_score = 0 when tax_drag >= 5.0.
    # Warn reason is informational only when tax_drag is below threshold but between 2.5–5.0
    # (tax_score = 3). When tax_drag >= max_tax_drag_pct the score is 0 AND reason fires,
    # ensuring reason ↔ score consistency.
    if tax_drag > cfg.max_tax_drag_pct:
        _add_reason(reasons, "HIGH_TAX_DRAG", "warn", "税コスト影響が大きく税引後パフォーマンスを圧迫しています。")
        actions.append("tax_model と損失繰越条件を点検してください。")

    # ------------------------------------------------------------------
    # Executability (10 pts)
    # ------------------------------------------------------------------
    executability = 10
    if not daily_signal_ready:
        executability -= 5
        _add_reason(reasons, "DAILY_SIGNAL_NOT_READY", "warn", "日次シグナル生成の前提データが揃っていません。")
        actions.append("日次データ同期後に daily signal の再計算を実施してください。")
    if usable_us < cfg.min_usable_us_tickers or usable_jp < cfg.min_usable_jp_tickers:
        executability -= 5
    executability = max(0, executability)

    # ------------------------------------------------------------------
    # Data reliability (15 pts)
    # ------------------------------------------------------------------
    data_reliability = 15
    if not freshness_ok:
        data_reliability -= 6
    if cfg.require_strict_fill_policy and fill_policy != "strict":
        data_reliability -= 3
        _add_reason(reasons, "NON_STRICT_FILL_POLICY", "warn", "fill_policy が strict ではありません。")
        actions.append("fill_policy='strict' で再実行して欠損補完依存を減らしてください。")
    if not cache_isolation:
        data_reliability -= 3
    if not latest_dates_aligned:
        data_reliability -= 2
        _add_reason(reasons, "CACHE_DATES_NOT_ALIGNED", "warn", "US/JP の最新日付が揃っていません。")
        actions.append("キャッシュ日付を揃え、同一基準日で再評価してください。")
    if stale_tickers or missing_tickers:
        data_reliability -= 2
    data_reliability = max(0, data_reliability)

    # ------------------------------------------------------------------
    # Aggregate
    # ------------------------------------------------------------------
    category_scores = {
        "profitability": profitability,
        "stability": stability,
        "cost_resilience": cost_resilience,
        "executability": executability,
        "data_reliability": data_reliability,
    }

    category_decisions = {
        "profitability": _finalize_category(profitability, 30)[1],
        "stability": _finalize_category(stability, 25)[1],
        "cost_resilience": _finalize_category(cost_resilience, 20)[1],
        "executability": _finalize_category(executability, 10)[1],
        "data_reliability": _finalize_category(data_reliability, 15)[1],
    }

    overall_score = sum(category_scores.values())

    # ------------------------------------------------------------------
    # Overall decision (relaxed gate)
    # ------------------------------------------------------------------
    reason_codes = {r["code"] for r in reasons}
    has_critical_warn = (
        "HIGH_COST_DRAG" in reason_codes and "HIGH_TAX_DRAG" in reason_codes
    )
    warn_reasons = [r for r in reasons if r["severity"] == "warn"]
    warn_count = len(warn_reasons)

    if reject_codes:
        overall_decision = "reject"
    elif overall_score >= 80 and not has_critical_warn:
        overall_decision = "pass"
    elif overall_score >= 75 and warn_count <= 1 and not has_critical_warn:
        overall_decision = "pass"
    elif overall_score >= 60:
        overall_decision = "hold"
    else:
        overall_decision = "reject"

    if overall_decision == "pass":
        summary = f"{payload.strategy_name} は主要閾値を満たしており、実践投入候補です。"
    elif overall_decision == "hold":
        summary = f"{payload.strategy_name} は一定の妥当性があるものの、追加検証が必要です。"
    else:
        summary = f"{payload.strategy_name} はデータ品質または主要リスク条件に抵触し、却下です。"

    if not actions:
        actions = ["現状の設定でフォワード検証を継続してください。"]

    unique_actions = list(dict.fromkeys(actions))

    # ------------------------------------------------------------------
    # Debug info added to metrics_snapshot
    # ------------------------------------------------------------------
    metrics["profitability_components"] = {  # type: ignore[assignment]
        "ar_score": _ar_score,
        "rr_penalty": _prof_rr_penalty,
    }
    metrics["stability_components"] = {  # type: ignore[assignment]
        "mdd_score": _mdd_score,
        "rr_penalty": _stab_rr_penalty,
    }
    metrics["cost_resilience_components"] = {  # type: ignore[assignment]
        "market_cost_score": _market_cost_score,
        "tax_score": _tax_score,
    }
    metrics["decision_gate_summary"] = {  # type: ignore[assignment]
        "has_critical_warn": has_critical_warn,
        "warn_count": warn_count,
        "reject_reasons": reject_codes,
    }

    return {
        "overall_decision": overall_decision,
        "overall_score": int(overall_score),
        "summary": summary,
        "category_scores": category_scores,
        "category_decisions": category_decisions,
        "reasons": reasons,
        "metrics_snapshot": metrics,
        "actions": unique_actions,
    }
