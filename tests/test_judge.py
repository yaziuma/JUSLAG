from __future__ import annotations

from juslag.judge import JudgeInput, JudgeThresholdConfig, judge_backtest


def _payload(
    *,
    after_tax_ar: float,
    after_tax_rr: float,
    after_tax_mdd: float,
    freshness_ok: bool = True,
    cache_isolation: bool = True,
    fill_policy: str = "strict",
    cost_drag: float = 1.2,
    tax_drag: float = 1.0,
) -> JudgeInput:
    gross_ar = after_tax_ar + tax_drag + cost_drag
    pre_tax_ar = after_tax_ar + tax_drag
    return JudgeInput(
        strategy_name="PCA SUB",
        performance_sets={
            "gross": [{"AR(%)": gross_ar, "Risk(%)": 9.0, "R/R": 0.9, "MDD(%)": -8.0, "N_days": 252}],
            "net_pre_tax": [{"AR(%)": pre_tax_ar, "Risk(%)": 9.5, "R/R": 0.7, "MDD(%)": -12.0, "N_days": 252}],
            "net_after_tax": [
                {
                    "AR(%)": after_tax_ar,
                    "Risk(%)": 10.0,
                    "R/R": after_tax_rr,
                    "MDD(%)": after_tax_mdd,
                    "N_days": 252,
                }
            ],
        },
        cost_breakdown={"commission_total": 1.0, "slippage_total": 1.0, "borrow_total": 0.2, "tax_total": 0.8},
        data_quality={
            "fill_policy": fill_policy,
            "price_mode": "adjusted",
            "cache_isolated_by_price_mode": cache_isolation,
            "usable_us_tickers": 10,
            "usable_jp_tickers": 16,
            "filled_cells": 0,
        },
        freshness={
            "freshness_ok": freshness_ok,
            "stale_tickers": [],
            "missing_tickers": [],
        },
        cache_summary={
            "latest_dates_aligned": True,
            "daily_signal_ready": True,
        },
    )


# ---------------------------------------------------------------------------
# Existing tests (preserved / updated for new pass gate)
# ---------------------------------------------------------------------------

def test_judge_backtest_pass_case() -> None:
    result = judge_backtest(_payload(after_tax_ar=8.6, after_tax_rr=0.72, after_tax_mdd=-9.0))

    assert result["overall_decision"] == "pass"


def test_judge_backtest_hold_or_warn_case() -> None:
    result = judge_backtest(
        _payload(
            after_tax_ar=2.0,
            after_tax_rr=0.24,
            after_tax_mdd=-19.0,
            cost_drag=2.7,
        )
    )

    assert result["overall_decision"] in {"hold", "warn", "reject"}
    assert result["overall_decision"] != "pass"


def test_judge_backtest_warn_or_reject_case() -> None:
    result = judge_backtest(_payload(after_tax_ar=-1.8, after_tax_rr=-0.1, after_tax_mdd=-28.0))

    assert result["overall_decision"] in {"hold", "warn", "reject"}


def test_judge_backtest_reject_case() -> None:
    result = judge_backtest(
        _payload(
            after_tax_ar=3.2,
            after_tax_rr=0.35,
            after_tax_mdd=-18.0,
            freshness_ok=False,
            cache_isolation=False,
        )
    )

    assert result["overall_decision"] == "reject"


def test_judge_backtest_reason_codes() -> None:
    result = judge_backtest(
        _payload(
            after_tax_ar=1.5,
            after_tax_rr=0.2,
            after_tax_mdd=-22.0,
            freshness_ok=False,
            cache_isolation=False,
            cost_drag=3.8,
        )
    )

    codes = {r["code"] for r in result["reasons"]}

    assert "LOW_AFTER_TAX_RETURN" in codes
    assert "HIGH_COST_DRAG" in codes
    assert "DATA_FRESHNESS_FAILED" in codes
    assert "CACHE_ISOLATION_FAILED" in codes


# ---------------------------------------------------------------------------
# New tests
# ---------------------------------------------------------------------------

def test_cost_drag_improvement_raises_cost_score() -> None:
    """cost_dragだけ改善（3.0 → 2.5）でcost_resilience_scoreが上がること。"""
    result_before = judge_backtest(_payload(after_tax_ar=6.0, after_tax_rr=0.5, after_tax_mdd=-12.0, cost_drag=3.0, tax_drag=1.0))
    result_after = judge_backtest(_payload(after_tax_ar=6.0, after_tax_rr=0.5, after_tax_mdd=-12.0, cost_drag=2.5, tax_drag=1.0))

    # cost_drag=3.0 → market_cost_score=6, cost_drag=2.5 → market_cost_score=6 (still < 3.0)
    # Actually 3.0 is exactly the boundary: < 3.0 => 6, >= 3.0 means 3 (< 4.0 => 3).
    # 3.0 is NOT < 3.0, so it gets market_cost_score=3. 2.5 < 3.0, so it gets 6.
    score_before = result_before["category_scores"]["cost_resilience"]
    score_after = result_after["category_scores"]["cost_resilience"]
    assert score_after > score_before, (
        f"Expected cost_resilience to improve: {score_before} -> {score_after}"
    )


def test_tax_drag_improvement_raises_tax_score() -> None:
    """tax_dragだけ改善（3.0 → 1.5）でtax_scoreが上がること。"""
    # tax_drag=3.0 → tax_score=3 (>= 2.5, < 5.0)
    # tax_drag=1.5 → tax_score=6 (>= 1.0, < 2.5)
    result_before = judge_backtest(_payload(after_tax_ar=6.0, after_tax_rr=0.5, after_tax_mdd=-12.0, cost_drag=1.0, tax_drag=3.0))
    result_after = judge_backtest(_payload(after_tax_ar=6.0, after_tax_rr=0.5, after_tax_mdd=-12.0, cost_drag=1.0, tax_drag=1.5))

    score_before = result_before["category_scores"]["cost_resilience"]
    score_after = result_after["category_scores"]["cost_resilience"]
    assert score_after > score_before, (
        f"Expected cost_resilience (tax portion) to improve: {score_before} -> {score_after}"
    )

    # Verify via components
    comp_before = result_before["metrics_snapshot"]["cost_resilience_components"]
    comp_after = result_after["metrics_snapshot"]["cost_resilience_components"]
    assert comp_after["tax_score"] > comp_before["tax_score"]


def test_mdd_improvement_raises_stability_score() -> None:
    """MDDが少し改善（-18 → -16）でstability_scoreが上がること。"""
    # mdd=-18 → mdd >= -20 → mdd_score=16
    # mdd=-16 → mdd >= -17.5 → mdd_score=18
    result_before = judge_backtest(_payload(after_tax_ar=5.0, after_tax_rr=0.4, after_tax_mdd=-18.0))
    result_after = judge_backtest(_payload(after_tax_ar=5.0, after_tax_rr=0.4, after_tax_mdd=-16.0))

    score_before = result_before["category_scores"]["stability"]
    score_after = result_after["category_scores"]["stability"]
    assert score_after > score_before, (
        f"Expected stability_score to improve: {score_before} -> {score_after}"
    )


def test_high_score_with_one_warn_is_pass() -> None:
    """warn1件だけの高得点（80点以上）でPASSになること。"""
    # ar=8.6 → profitability=28 (rr=0.72, no rr penalty, ar_score=28)
    # mdd=-9.0 → stability=25
    # cost_drag=1.2 → market_cost=9, tax_drag=1.0 → tax_score=6, cost_resilience=15
    # executability=10, data_reliability=15
    # total = 28 + 25 + 15 + 10 + 15 = 93
    # warn: LOW_AFTER_TAX_RR because rr=0.25 < 0.30
    result = judge_backtest(_payload(after_tax_ar=8.6, after_tax_rr=0.25, after_tax_mdd=-9.0))

    warn_codes = [r["code"] for r in result["reasons"] if r["severity"] == "warn"]
    assert len(warn_codes) == 1, f"Expected exactly 1 warn, got: {warn_codes}"
    assert result["overall_score"] >= 80
    assert result["overall_decision"] == "pass"


def test_critical_warn_high_cost_and_tax_drag_stays_hold() -> None:
    """HIGH_COST_DRAG + HIGH_TAX_DRAG 同時でHOLD維持すること（passにならない）。"""
    # cost_drag > max_cost_drag_pct(3.0) → HIGH_COST_DRAG
    # tax_drag > max_tax_drag_pct(5.0) → HIGH_TAX_DRAG
    # Both together → has_critical_warn = True → cannot be pass
    result = judge_backtest(
        _payload(
            after_tax_ar=8.6,
            after_tax_rr=0.72,
            after_tax_mdd=-9.0,
            cost_drag=4.0,
            tax_drag=6.0,
        )
    )

    codes = {r["code"] for r in result["reasons"]}
    assert "HIGH_COST_DRAG" in codes
    assert "HIGH_TAX_DRAG" in codes

    gate = result["metrics_snapshot"]["decision_gate_summary"]
    assert gate["has_critical_warn"] is True

    assert result["overall_decision"] != "pass", (
        f"Expected not pass due to critical warn, got {result['overall_decision']}"
    )


def test_high_tax_drag_penalises_tax_score() -> None:
    """HIGH_TAX_DRAGが出るとき tax_score が減点されていること（reason ↔ score 整合）。"""
    cfg = JudgeThresholdConfig(max_tax_drag_pct=5.0)
    # tax_drag=6.0 → HIGH_TAX_DRAG reason + tax_score=0
    result = judge_backtest(
        _payload(after_tax_ar=6.0, after_tax_rr=0.5, after_tax_mdd=-12.0, cost_drag=1.0, tax_drag=6.0),
        thresholds=cfg,
    )

    codes = {r["code"] for r in result["reasons"]}
    assert "HIGH_TAX_DRAG" in codes

    comp = result["metrics_snapshot"]["cost_resilience_components"]
    assert comp["tax_score"] == 0, (
        f"Expected tax_score=0 when HIGH_TAX_DRAG fires, got {comp['tax_score']}"
    )


def test_total_max_score_is_100() -> None:
    """総配点が100点であること。"""
    # Perfect strategy: all scores at maximum
    result = judge_backtest(
        _payload(
            after_tax_ar=10.0,   # ar_score=30
            after_tax_rr=1.0,    # no rr_penalty
            after_tax_mdd=-5.0,  # mdd_score=25
            cost_drag=0.5,       # market_cost_score=12
            tax_drag=0.5,        # tax_score=8
        )
    )

    scores = result["category_scores"]
    assert scores["profitability"] == 30, f"profitability: {scores['profitability']}"
    assert scores["stability"] == 25, f"stability: {scores['stability']}"
    assert scores["cost_resilience"] == 20, f"cost_resilience: {scores['cost_resilience']}"
    assert scores["executability"] == 10, f"executability: {scores['executability']}"
    assert scores["data_reliability"] == 15, f"data_reliability: {scores['data_reliability']}"

    total = sum(scores.values())
    assert total == 100, f"Expected total=100, got {total}"
