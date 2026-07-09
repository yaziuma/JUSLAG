from __future__ import annotations

from juslag.strategies.base import StrategyRule, abs_le
from juslag.strategies.context import StrategyContext
from juslag.strategies.decision import StrategyDecision


class Rule406NoFlip(StrategyRule):
    rule_id = "rule_406_no_flip"
    rule_name_ja = "GapOvht + 寄りgap制限 + 弱rotation除外（LONG反転なし）"
    description_ja = (
        "rule_406 から SHORT過熱時の LONG反転ロジックを除いたバリアント。"
        "寄り付きgapが1.5%を超える日、またはsector rotationが弱い日は見送る。"
        "それ以外は常にGapOvht除外OCを実行する。"
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

        return StrategyDecision(
            selected_strategy="gap_ovht_oc",
            rule_id=self.rule_id,
            rule_name_ja=self.rule_name_ja,
            action="execute",
            reason_ja="フィルタ条件を満たすためGapOvht除外OCを実行",
            default_strategy=self.default_strategy,
        )
