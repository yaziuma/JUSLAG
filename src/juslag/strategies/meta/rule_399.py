from __future__ import annotations

from juslag.strategies.base import StrategyRule, abs_gt, ge
from juslag.strategies.context import StrategyContext
from juslag.strategies.decision import StrategyDecision


class Rule399StrongSignalHighVolFlip(StrategyRule):
    rule_id = "rule_399"
    rule_name_ja = "GapOvht + 強シグナル選別 + 高ボラgap時LONG反転"
    description_ja = (
        "普段はGapOvht除外OCを使う。"
        "弱いシグナルの日は取引しない。"
        "高ボラかつ寄りgapが出た日は、日中リバーサルを警戒してLONG反転OCへ切り替える。"
        "稼働率は低いが、直近環境への適応候補。"
    )
    default_strategy = "gap_ovht_oc"

    def decide(self, context: StrategyContext) -> StrategyDecision:
        if not ge(context.candidate_signal_strength, 0.3):
            return StrategyDecision(
                selected_strategy="skip",
                rule_id=self.rule_id,
                rule_name_ja=self.rule_name_ja,
                action="skip",
                reason_ja="candidate_signal_strength が0.3未満、または欠損のため見送り",
                default_strategy=self.default_strategy,
                matched_filter="candidate_signal_strength >= 0.3",
            )

        if context.vol_regime == "high_vol" and abs_gt(context.open_gap, 0.005):
            return StrategyDecision(
                selected_strategy="long_flip_oc",
                rule_id=self.rule_id,
                rule_name_ja=self.rule_name_ja,
                action="override",
                reason_ja="high_vol かつ寄りgap絶対値が0.5%超のため、LONG反転OCへ切り替え",
                default_strategy=self.default_strategy,
                override_strategy="long_flip_oc",
                matched_override="vol_regime == high_vol and abs_open_gap > 0.5%",
            )

        return StrategyDecision(
            selected_strategy="gap_ovht_oc",
            rule_id=self.rule_id,
            rule_name_ja=self.rule_name_ja,
            action="execute",
            reason_ja="強シグナルで切替条件に該当しないためGapOvht除外OCを実行",
            default_strategy=self.default_strategy,
        )
