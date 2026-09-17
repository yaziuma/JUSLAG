from __future__ import annotations

from juslag.strategies.base import StrategyRule
from juslag.strategies.context import StrategyContext
from juslag.strategies.decision import StrategyDecision


class PreopenNoGap(StrategyRule):
    """Research-only ablation of rule_406_no_flip; not registered for production."""

    rule_id = "research_preopen_no_gap"
    rule_name_ja = "寄り前確定情報のみ・弱rotation除外"
    description_ja = "現行ルールから当日寄りgapの全利用を除いた研究用アブレーション。"
    default_strategy = "curr_oc"

    def decide(self, context: StrategyContext) -> StrategyDecision:
        skip = context.rotation_regime == "weak_rotation"
        return StrategyDecision(
            selected_strategy="skip" if skip else "curr_oc",
            rule_id=self.rule_id,
            rule_name_ja=self.rule_name_ja,
            action="skip" if skip else "execute",
            reason_ja="弱rotation" if skip else "寄り前条件を満たす",
            default_strategy=self.default_strategy,
        )
