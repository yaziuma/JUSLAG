from __future__ import annotations

import pytest

from juslag.strategies import get_rule, list_rules, rule_ids, StrategyContext
from juslag.strategies.registry import get_rule


def _ctx(**kwargs) -> StrategyContext:
    defaults = dict(
        signal_date="2026-01-15",
        candidate_signal_strength=None,
        open_gap=None,
        long_gap=None,
        short_gap=None,
        trend_regime=None,
        vol_regime=None,
        rotation_regime=None,
    )
    defaults.update(kwargs)
    return StrategyContext(**defaults)


# ---------------------------------------------------------------------------
# Rule 406 tests
# ---------------------------------------------------------------------------

class TestRule406:
    def setup_method(self):
        self.rule = get_rule("rule_406")

    def test_normal_execute(self):
        d = self.rule.decide(_ctx(open_gap=0.010, rotation_regime="mid_rotation", short_gap=0.005))
        assert d.action == "execute"
        assert d.selected_strategy == "gap_ovht_oc"

    def test_open_gap_overheat_skip(self):
        d = self.rule.decide(_ctx(open_gap=0.020, rotation_regime="mid_rotation", short_gap=0.005))
        assert d.action == "skip"

    def test_weak_rotation_skip(self):
        d = self.rule.decide(_ctx(open_gap=0.010, rotation_regime="weak_rotation", short_gap=0.005))
        assert d.action == "skip"

    def test_short_gap_overheat_override(self):
        d = self.rule.decide(_ctx(open_gap=0.010, rotation_regime="mid_rotation", short_gap=0.015))
        assert d.action == "override"
        assert d.selected_strategy == "long_flip_oc"

    def test_open_gap_none_skip(self):
        d = self.rule.decide(_ctx(open_gap=None, rotation_regime="mid_rotation", short_gap=0.005))
        assert d.action == "skip"

    def test_boundary_open_gap_exactly_015(self):
        # abs(0.015) <= 0.015 → should NOT skip
        d = self.rule.decide(_ctx(open_gap=0.015, rotation_regime="mid_rotation", short_gap=0.005))
        assert d.action == "execute"

    def test_boundary_short_gap_exactly_010(self):
        # abs(0.010) > 0.010 is False → should NOT override
        d = self.rule.decide(_ctx(open_gap=0.010, rotation_regime="mid_rotation", short_gap=0.010))
        assert d.action == "execute"


# ---------------------------------------------------------------------------
# Rule 399 tests
# ---------------------------------------------------------------------------

class TestRule399:
    def setup_method(self):
        self.rule = get_rule("rule_399")

    def test_weak_signal_skip(self):
        d = self.rule.decide(_ctx(candidate_signal_strength=0.2))
        assert d.action == "skip"

    def test_none_signal_skip(self):
        d = self.rule.decide(_ctx(candidate_signal_strength=None))
        assert d.action == "skip"

    def test_strong_signal_execute(self):
        d = self.rule.decide(_ctx(candidate_signal_strength=0.4, vol_regime="mid_vol", open_gap=0.002))
        assert d.action == "execute"
        assert d.selected_strategy == "gap_ovht_oc"

    def test_high_vol_large_gap_override(self):
        d = self.rule.decide(_ctx(candidate_signal_strength=0.4, vol_regime="high_vol", open_gap=0.010))
        assert d.action == "override"
        assert d.selected_strategy == "long_flip_oc"


# ---------------------------------------------------------------------------
# Rule 13 tests
# ---------------------------------------------------------------------------

class TestRule13:
    def setup_method(self):
        self.rule = get_rule("rule_13")

    def test_low_vol_mid_rotation_skip(self):
        d = self.rule.decide(_ctx(vol_regime="mid_vol", rotation_regime="mid_rotation"))
        assert d.action == "skip"

    def test_high_vol_execute(self):
        d = self.rule.decide(_ctx(vol_regime="high_vol", rotation_regime="mid_rotation", short_gap=0.005))
        assert d.action == "execute"

    def test_strong_rotation_execute(self):
        d = self.rule.decide(_ctx(vol_regime="mid_vol", rotation_regime="strong_rotation", short_gap=0.005))
        assert d.action == "execute"

    def test_short_gap_override_short_only(self):
        d = self.rule.decide(_ctx(vol_regime="high_vol", rotation_regime="mid_rotation", short_gap=0.015))
        assert d.action == "override"
        assert d.selected_strategy == "short_only_oc"


# ---------------------------------------------------------------------------
# Rule 87 tests
# ---------------------------------------------------------------------------

class TestRule87:
    def setup_method(self):
        self.rule = get_rule("rule_87")

    def test_low_vol_skip(self):
        d = self.rule.decide(_ctx(vol_regime="low_vol", rotation_regime="mid_rotation"))
        assert d.action == "skip"

    def test_high_vol_execute(self):
        d = self.rule.decide(_ctx(vol_regime="high_vol", rotation_regime="mid_rotation", short_gap=0.005))
        assert d.action == "execute"

    def test_short_gap_override_lgap(self):
        d = self.rule.decide(_ctx(vol_regime="high_vol", rotation_regime="mid_rotation", short_gap=0.010))
        assert d.action == "override"
        assert d.selected_strategy == "lgap_oc"


# ---------------------------------------------------------------------------
# Rule 1357 tests
# ---------------------------------------------------------------------------

class TestRule1357:
    def setup_method(self):
        self.rule = get_rule("rule_1357")

    def test_sideways_skip(self):
        d = self.rule.decide(_ctx(trend_regime="sideways"))
        assert d.action == "skip"

    def test_none_trend_skip(self):
        d = self.rule.decide(_ctx(trend_regime=None))
        assert d.action == "skip"

    def test_uptrend_execute(self):
        d = self.rule.decide(_ctx(trend_regime="uptrend", open_gap=0.005))
        assert d.action == "execute"

    def test_downtrend_execute(self):
        d = self.rule.decide(_ctx(trend_regime="downtrend", open_gap=0.003))
        assert d.action == "execute"

    def test_open_gap_overheat_override_lgap(self):
        d = self.rule.decide(_ctx(trend_regime="uptrend", open_gap=0.010))
        assert d.action == "override"
        assert d.selected_strategy == "lgap_oc"


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

def test_list_rules_contains_all():
    ids = rule_ids()
    assert "rule_406" in ids
    assert "rule_399" in ids
    assert "rule_13" in ids
    assert "rule_87" in ids
    assert "rule_1357" in ids
    assert "rolling3_selector" in ids


def test_get_unknown_rule_raises():
    with pytest.raises(ValueError):
        get_rule("rule_9999")


def test_decision_to_dict():
    rule = get_rule("rule_406")
    d = rule.decide(_ctx(open_gap=0.010, rotation_regime="mid_rotation", short_gap=0.005))
    result = d.to_dict()
    assert "selected_strategy" in result
    assert "action" in result
    assert "rule_id" in result
    assert "reason_ja" in result
