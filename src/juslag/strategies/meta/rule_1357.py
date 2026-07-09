from __future__ import annotations

from juslag.strategies.base import StrategyRule, abs_gt
from juslag.strategies.context import StrategyContext
from juslag.strategies.decision import StrategyDecision


class Rule1357TrendLGapSwitch(StrategyRule):
    rule_id = "rule_1357"
    rule_name_ja = "GapOvht + 方向性相場限定 + 寄りgap過熱時LGap切替"
    description_ja = (
        "普段はGapOvht除外OCを使う。"
        "横ばい相場を避け、上昇または下降の方向性がある日だけ取引する。"
        "寄り付きgapが過熱した場合はLGapへ切り替える。"
        "補助候補。単独本命ではない。"
    )
    default_strategy = "gap_ovht_oc"

    def decide(self, context: StrategyContext) -> StrategyDecision:
        if context.trend_regime not in ("uptrend", "downtrend"):
            return StrategyDecision(
                selected_strategy="skip",
                rule_id=self.rule_id,
                rule_name_ja=self.rule_name_ja,
                action="skip",
                reason_ja="trend_regime が sideways または欠損のため見送り",
                default_strategy=self.default_strategy,
                matched_filter="trend_regime in (uptrend, downtrend)",
            )

        if abs_gt(context.open_gap, 0.0075):
            return StrategyDecision(
                selected_strategy="lgap_oc",
                rule_id=self.rule_id,
                rule_name_ja=self.rule_name_ja,
                action="override",
                reason_ja="寄りgap絶対値が0.75%を超えたため、LGap除外OCへ切り替え",
                default_strategy=self.default_strategy,
                override_strategy="lgap_oc",
                matched_override="abs_open_gap > 0.75%",
            )

        return StrategyDecision(
            selected_strategy="gap_ovht_oc",
            rule_id=self.rule_id,
            rule_name_ja=self.rule_name_ja,
            action="execute",
            reason_ja="方向性相場でgap過熱なし、GapOvht除外OCを実行",
            default_strategy=self.default_strategy,
        )
