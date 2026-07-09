from __future__ import annotations

from abc import ABC, abstractmethod

from juslag.strategies.context import StrategyContext
from juslag.strategies.decision import StrategyDecision


def abs_gt(value: float | None, threshold: float) -> bool:
    return value is not None and abs(value) > threshold


def abs_le(value: float | None, threshold: float) -> bool:
    return value is not None and abs(value) <= threshold


def ge(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


class StrategyRule(ABC):
    rule_id: str
    rule_name_ja: str
    description_ja: str
    default_strategy: str

    @abstractmethod
    def decide(self, context: StrategyContext) -> StrategyDecision:
        pass
