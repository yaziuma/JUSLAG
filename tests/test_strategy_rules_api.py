"""
strategy rule レジストリのライブラリ層カバレッジ。

旧 webui `/api/strategy-rules*` の HTTP アサーションは削除し、
juslag.strategies のレジストリ・decide() を直接検証する。
アクティブルールの永続化（旧SQLite）は廃止されたためテスト対象外。
"""
from __future__ import annotations

import pytest

from juslag.strategies import StrategyContext, get_rule, list_rules, rule_ids
from juslag.strategies.descriptions.rules_ja import RULE_DESCRIPTIONS_JA


def test_list_rules_includes_known_ids() -> None:
    ids = [rule.rule_id for rule in list_rules()]
    for expected in ["rule_406", "rule_399", "rule_13", "rule_87", "rule_1357", "rolling3_selector"]:
        assert expected in ids


def test_rule_ids_matches_list_rules() -> None:
    assert set(rule_ids()) == {rule.rule_id for rule in list_rules()}


def test_get_rule_returns_rule_with_matching_id() -> None:
    rule = get_rule("rule_406")
    assert rule.rule_id == "rule_406"


def test_get_unknown_rule_raises_value_error() -> None:
    with pytest.raises(ValueError):
        get_rule("rule_99999")


def test_rule_406_execute_case() -> None:
    rule = get_rule("rule_406")
    context = StrategyContext(
        signal_date="2026-01-15",
        candidate_signal_strength=0.4,
        open_gap=0.010,
        long_gap=None,
        short_gap=0.005,
        trend_regime="uptrend",
        vol_regime="mid_vol",
        rotation_regime="mid_rotation",
    )
    decision = rule.decide(context)
    assert decision.action == "execute"
    assert decision.selected_strategy == "gap_ovht_oc"


def test_rule_406_skip_case_on_large_open_gap() -> None:
    rule = get_rule("rule_406")
    context = StrategyContext(
        signal_date="2026-01-15",
        candidate_signal_strength=None,
        open_gap=0.020,  # > 1.5% → skip
        long_gap=None,
        short_gap=None,
        trend_regime=None,
        vol_regime=None,
        rotation_regime=None,
    )
    decision = rule.decide(context)
    assert decision.action == "skip"


def test_rule_descriptions_include_rule_406() -> None:
    assert "rule_406" in RULE_DESCRIPTIONS_JA
