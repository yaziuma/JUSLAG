from __future__ import annotations

from juslag.strategies.base import StrategyRule
from juslag.strategies.meta.rule_406 import Rule406OpenGapRotShortFlip
from juslag.strategies.meta.rule_406_no_flip import Rule406NoFlip
from juslag.strategies.meta.rule_399 import Rule399StrongSignalHighVolFlip
from juslag.strategies.meta.rule_13 import Rule13HighVolRotationShortOnly
from juslag.strategies.meta.rule_87 import Rule87LGapSwitch
from juslag.strategies.meta.rule_1357 import Rule1357TrendLGapSwitch
from juslag.strategies.meta.rolling3_selector import Rolling3RuleSelector

_BASE_RULES: dict[str, StrategyRule] = {
    "rule_406": Rule406OpenGapRotShortFlip(),
    "rule_406_no_flip": Rule406NoFlip(),
    "rule_399": Rule399StrongSignalHighVolFlip(),
    "rule_13": Rule13HighVolRotationShortOnly(),
    "rule_87": Rule87LGapSwitch(),
    "rule_1357": Rule1357TrendLGapSwitch(),
}

_RULES: dict[str, StrategyRule] = {
    **_BASE_RULES,
    "rolling3_selector": Rolling3RuleSelector(inner_registry=_BASE_RULES),
}


def get_rule(rule_id: str) -> StrategyRule:
    try:
        return _RULES[rule_id]
    except KeyError:
        raise ValueError(f"Unknown strategy rule_id: {rule_id}")


def list_rules() -> list[StrategyRule]:
    return list(_RULES.values())


def rule_ids() -> list[str]:
    return list(_RULES.keys())
