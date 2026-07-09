from __future__ import annotations

from juslag.strategies.base import StrategyRule, abs_gt
from juslag.strategies.context import StrategyContext
from juslag.strategies.decision import StrategyDecision


class Rule13HighVolRotationShortOnly(StrategyRule):
    rule_id = "rule_13"
    rule_name_ja = "GapOvht + 高ボラ/強rotation限定 + SHORT過熱時SHORT単独"
    description_ja = (
        "普段はGapOvht除外OCを使う。"
        "動きのある日（high_vol または strong_rotation）だけ取引する。"
        "SHORT側gapが大きい日は、LONG反転ではなくSHORT単独に切り替える。"
        "防御寄りのメタ戦略。"
    )
    default_strategy = "gap_ovht_oc"

    def decide(self, context: StrategyContext) -> StrategyDecision:
        active = context.vol_regime == "high_vol" or context.rotation_regime == "strong_rotation"
        if not active:
            return StrategyDecision(
                selected_strategy="skip",
                rule_id=self.rule_id,
                rule_name_ja=self.rule_name_ja,
                action="skip",
                reason_ja="high_vol でも strong_rotation でもないため見送り",
                default_strategy=self.default_strategy,
                matched_filter="vol_regime == high_vol or rotation_regime == strong_rotation",
            )

        if abs_gt(context.short_gap, 0.010):
            return StrategyDecision(
                selected_strategy="short_only_oc",
                rule_id=self.rule_id,
                rule_name_ja=self.rule_name_ja,
                action="override",
                reason_ja="SHORT側gapが1.0%を超えたため、SHORT単独OCへ切り替え",
                default_strategy=self.default_strategy,
                override_strategy="short_only_oc",
                matched_override="abs_short_gap > 1.0%",
            )

        return StrategyDecision(
            selected_strategy="gap_ovht_oc",
            rule_id=self.rule_id,
            rule_name_ja=self.rule_name_ja,
            action="execute",
            reason_ja="動きのある相場でSHORT過熱なし、GapOvht除外OCを実行",
            default_strategy=self.default_strategy,
        )
