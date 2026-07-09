from __future__ import annotations

from juslag.strategies.base import StrategyRule, abs_gt, abs_le
from juslag.strategies.context import StrategyContext
from juslag.strategies.decision import StrategyDecision


class Rule406OpenGapRotShortFlip(StrategyRule):
    rule_id = "rule_406"
    rule_name_ja = "GapOvht + 寄りgap制限 + 弱rotation除外 + SHORT過熱時LONG反転"
    description_ja = (
        "普段はGapOvht除外OCを使う。"
        "ただし、寄り付きgapが1.5%を超える日、またはsector rotationが弱い日は見送る。"
        "SHORT側gapが1.0%を超える日は、寄り付きでSHORT側が過熱している可能性があるため、LONG反転OCへ切り替える。"
    )
    default_strategy = "gap_ovht_oc"

    def decide(self, context: StrategyContext) -> StrategyDecision:
        if not abs_le(context.open_gap, 0.015):
            return StrategyDecision(
                selected_strategy="skip",
                rule_id=self.rule_id,
                rule_name_ja=self.rule_name_ja,
                action="skip",
                reason_ja="寄りgapが1.5%を超える、または欠損のため見送り",
                default_strategy=self.default_strategy,
                matched_filter="abs_open_gap <= 1.5%",
            )

        if context.rotation_regime == "weak_rotation":
            return StrategyDecision(
                selected_strategy="skip",
                rule_id=self.rule_id,
                rule_name_ja=self.rule_name_ja,
                action="skip",
                reason_ja="rotation_regime が weak_rotation のため見送り",
                default_strategy=self.default_strategy,
                matched_filter="rotation_regime != weak_rotation",
            )

        if abs_gt(context.short_gap, 0.010):
            return StrategyDecision(
                selected_strategy="long_flip_oc",
                rule_id=self.rule_id,
                rule_name_ja=self.rule_name_ja,
                action="override",
                reason_ja="SHORT側gapが1.0%を超えたため、LONG反転OCへ切り替え",
                default_strategy=self.default_strategy,
                override_strategy="long_flip_oc",
                matched_override="abs_short_gap > 1.0%",
            )

        return StrategyDecision(
            selected_strategy="gap_ovht_oc",
            rule_id=self.rule_id,
            rule_name_ja=self.rule_name_ja,
            action="execute",
            reason_ja="フィルタ条件を満たし、切替条件に該当しないためGapOvht除外OCを実行",
            default_strategy=self.default_strategy,
        )
