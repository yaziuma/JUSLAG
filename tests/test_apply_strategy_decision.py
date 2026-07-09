from __future__ import annotations

import pandas as pd
import pytest

from juslag.signal import DailySignalResult, GAP_FILTER_THRESHOLD, apply_strategy_decision


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_result(**positions: str) -> DailySignalResult:
    """position dict から最小限の DailySignalResult を生成する。"""
    tickers = list(positions.keys())
    table = pd.DataFrame(
        {
            "sector": ["s"] * len(tickers),
            "signal": [0.0] * len(tickers),
            "position": list(positions.values()),
        },
        index=tickers,
    )
    long_n = sum(1 for v in positions.values() if v == "LONG")
    short_n = sum(1 for v in positions.values() if v == "SHORT")
    return DailySignalResult(
        table=table,
        signal_reference_us_date=pd.Timestamp("2026-01-15"),
        execution_target_jp_date=pd.Timestamp("2026-01-16"),
        adopted_long_count=long_n,
        adopted_short_count=short_n,
    )


def _gap(mapping: dict[str, float]) -> pd.Series:
    return pd.Series(mapping)


# ---------------------------------------------------------------------------
# skip
# ---------------------------------------------------------------------------

class TestSkip:
    def test_all_positions_become_neutral(self):
        r = _make_result(A="LONG", B="SHORT", C="neutral")
        out = apply_strategy_decision(r, "skip")
        assert (out.table["position"] == "neutral").all()

    def test_adopted_counts_are_zero(self):
        r = _make_result(A="LONG", B="SHORT")
        out = apply_strategy_decision(r, "skip")
        assert out.adopted_long_count == 0
        assert out.adopted_short_count == 0

    def test_selected_strategy_field_is_set(self):
        r = _make_result(A="LONG")
        out = apply_strategy_decision(r, "skip")
        assert out.selected_strategy == "skip"

    def test_original_result_is_not_mutated(self):
        r = _make_result(A="LONG", B="SHORT")
        apply_strategy_decision(r, "skip")
        assert r.table.loc["A", "position"] == "LONG"


# ---------------------------------------------------------------------------
# long_flip_oc
# ---------------------------------------------------------------------------

class TestLongFlipOc:
    def test_long_becomes_short(self):
        r = _make_result(A="LONG", B="SHORT", C="neutral")
        out = apply_strategy_decision(r, "long_flip_oc")
        assert out.table.loc["A", "position"] == "SHORT"

    def test_existing_short_stays_short(self):
        r = _make_result(A="LONG", B="SHORT")
        out = apply_strategy_decision(r, "long_flip_oc")
        assert out.table.loc["B", "position"] == "SHORT"

    def test_neutral_stays_neutral(self):
        r = _make_result(A="LONG", B="SHORT", C="neutral")
        out = apply_strategy_decision(r, "long_flip_oc")
        assert out.table.loc["C", "position"] == "neutral"

    def test_adopted_long_becomes_zero(self):
        r = _make_result(A="LONG", B="LONG", C="SHORT")
        out = apply_strategy_decision(r, "long_flip_oc")
        assert out.adopted_long_count == 0

    def test_adopted_short_includes_flipped_longs(self):
        r = _make_result(A="LONG", B="LONG", C="SHORT")
        out = apply_strategy_decision(r, "long_flip_oc")
        assert out.adopted_short_count == 3

    def test_selected_strategy_field_is_set(self):
        r = _make_result(A="LONG")
        out = apply_strategy_decision(r, "long_flip_oc")
        assert out.selected_strategy == "long_flip_oc"


# ---------------------------------------------------------------------------
# short_only_oc
# ---------------------------------------------------------------------------

class TestShortOnlyOc:
    def test_long_becomes_neutral(self):
        r = _make_result(A="LONG", B="SHORT", C="neutral")
        out = apply_strategy_decision(r, "short_only_oc")
        assert out.table.loc["A", "position"] == "neutral"

    def test_short_stays_short(self):
        r = _make_result(A="LONG", B="SHORT")
        out = apply_strategy_decision(r, "short_only_oc")
        assert out.table.loc["B", "position"] == "SHORT"

    def test_adopted_long_is_zero(self):
        r = _make_result(A="LONG", B="LONG", C="SHORT")
        out = apply_strategy_decision(r, "short_only_oc")
        assert out.adopted_long_count == 0

    def test_adopted_short_unchanged(self):
        r = _make_result(A="LONG", B="LONG", C="SHORT")
        out = apply_strategy_decision(r, "short_only_oc")
        assert out.adopted_short_count == 1


# ---------------------------------------------------------------------------
# gap_ovht_oc
# ---------------------------------------------------------------------------

class TestGapOvhtOc:
    def test_long_with_excess_positive_gap_removed(self):
        r = _make_result(A="LONG", B="SHORT")
        gap = _gap({"A": GAP_FILTER_THRESHOLD + 0.001, "B": -0.002})
        out = apply_strategy_decision(r, "gap_ovht_oc", overnight_gap=gap)
        assert out.table.loc["A", "position"] == "neutral"
        assert out.table.loc["B", "position"] == "SHORT"

    def test_short_with_excess_negative_gap_removed(self):
        r = _make_result(A="LONG", B="SHORT")
        gap = _gap({"A": 0.001, "B": -(GAP_FILTER_THRESHOLD + 0.001)})
        out = apply_strategy_decision(r, "gap_ovht_oc", overnight_gap=gap)
        assert out.table.loc["A", "position"] == "LONG"
        assert out.table.loc["B", "position"] == "neutral"

    def test_both_sides_excess_both_removed(self):
        r = _make_result(A="LONG", B="SHORT")
        gap = _gap({"A": GAP_FILTER_THRESHOLD + 0.001, "B": -(GAP_FILTER_THRESHOLD + 0.001)})
        out = apply_strategy_decision(r, "gap_ovht_oc", overnight_gap=gap)
        assert (out.table["position"] == "neutral").all()

    def test_long_at_exactly_threshold_is_kept(self):
        r = _make_result(A="LONG")
        gap = _gap({"A": GAP_FILTER_THRESHOLD})  # == thr, not >, so kept
        out = apply_strategy_decision(r, "gap_ovht_oc", overnight_gap=gap)
        assert out.table.loc["A", "position"] == "LONG"

    def test_no_gap_falls_back_to_curr_oc(self):
        r = _make_result(A="LONG", B="SHORT")
        out = apply_strategy_decision(r, "gap_ovht_oc", overnight_gap=None)
        assert out.table.loc["A", "position"] == "LONG"
        assert out.table.loc["B", "position"] == "SHORT"

    def test_ticker_absent_from_gap_series_is_unchanged(self):
        r = _make_result(A="LONG", B="SHORT")
        gap = _gap({"A": GAP_FILTER_THRESHOLD + 0.001})  # B absent
        out = apply_strategy_decision(r, "gap_ovht_oc", overnight_gap=gap)
        assert out.table.loc["A", "position"] == "neutral"
        assert out.table.loc["B", "position"] == "SHORT"  # absent → unchanged

    def test_counts_updated(self):
        r = _make_result(A="LONG", B="LONG", C="SHORT")
        gap = _gap({"A": GAP_FILTER_THRESHOLD + 0.001, "B": 0.001, "C": -0.001})
        out = apply_strategy_decision(r, "gap_ovht_oc", overnight_gap=gap)
        assert out.adopted_long_count == 1
        assert out.adopted_short_count == 1


# ---------------------------------------------------------------------------
# lgap_oc
# ---------------------------------------------------------------------------

class TestLGapOc:
    def test_long_with_excess_positive_gap_removed(self):
        r = _make_result(A="LONG", B="SHORT")
        gap = _gap({"A": GAP_FILTER_THRESHOLD + 0.001, "B": -(GAP_FILTER_THRESHOLD + 0.001)})
        out = apply_strategy_decision(r, "lgap_oc", overnight_gap=gap)
        assert out.table.loc["A", "position"] == "neutral"

    def test_short_side_not_affected_even_with_large_negative_gap(self):
        r = _make_result(A="LONG", B="SHORT")
        gap = _gap({"A": 0.001, "B": -(GAP_FILTER_THRESHOLD + 0.001)})
        out = apply_strategy_decision(r, "lgap_oc", overnight_gap=gap)
        assert out.table.loc["B", "position"] == "SHORT"  # SHORT は除外されない

    def test_long_at_exactly_threshold_is_kept(self):
        r = _make_result(A="LONG")
        gap = _gap({"A": GAP_FILTER_THRESHOLD})  # == thr, not >
        out = apply_strategy_decision(r, "lgap_oc", overnight_gap=gap)
        assert out.table.loc["A", "position"] == "LONG"

    def test_no_gap_falls_back_to_curr_oc(self):
        r = _make_result(A="LONG", B="SHORT")
        out = apply_strategy_decision(r, "lgap_oc", overnight_gap=None)
        assert out.table.loc["A", "position"] == "LONG"
        assert out.table.loc["B", "position"] == "SHORT"


# ---------------------------------------------------------------------------
# curr_oc — 変更なし
# ---------------------------------------------------------------------------

class TestCurrOc:
    def test_positions_unchanged(self):
        r = _make_result(A="LONG", B="SHORT", C="neutral")
        out = apply_strategy_decision(r, "curr_oc")
        assert out.table.loc["A", "position"] == "LONG"
        assert out.table.loc["B", "position"] == "SHORT"
        assert out.table.loc["C", "position"] == "neutral"

    def test_selected_strategy_field_set(self):
        r = _make_result(A="LONG")
        out = apply_strategy_decision(r, "curr_oc")
        assert out.selected_strategy == "curr_oc"

