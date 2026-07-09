from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from juslag.strategies.base import StrategyRule
from juslag.strategies.context import StrategyContext
from juslag.strategies.decision import StrategyDecision


class RuleSelector(ABC):
    @abstractmethod
    def select_rule_id(self, target_date: date) -> str:
        pass


class Rolling3RuleSelector(StrategyRule):
    """年次ルール選択型（事前計算テーブル方式）。

    year_rule_table: {year: rule_id} の形式で各年に使うルールIDを指定。
    対象年が table に存在しない場合は fallback_rule_id を使う。
    """

    rule_id = "rolling3_selector"
    rule_name_ja = "rolling3 年次メタルール選択"
    description_ja = (
        "毎年、直近3年の成績で上位ルールを選び、翌年はそのルールを使う。"
        "事前計算テーブル方式で実装。年初時点で選定したルールIDを記録する。"
        "選定履歴は必ず保存する。"
    )
    default_strategy = "gap_ovht_oc"

    def __init__(
        self,
        year_rule_table: dict[int, str] | None = None,
        fallback_rule_id: str = "rule_406",
        inner_registry: "dict[str, StrategyRule] | None" = None,
    ) -> None:
        self._year_rule_table: dict[int, str] = year_rule_table or {}
        self._fallback_rule_id = fallback_rule_id
        self._inner_registry = inner_registry or {}

    def select_rule_id(self, target_date: date) -> str:
        return self._year_rule_table.get(target_date.year, self._fallback_rule_id)

    def decide(self, context: StrategyContext) -> StrategyDecision:
        from datetime import date as date_cls
        target_date = date_cls.fromisoformat(context.signal_date)
        selected_rule_id = self.select_rule_id(target_date)
        inner_rule = self._inner_registry.get(selected_rule_id)
        if inner_rule is None:
            return StrategyDecision(
                selected_strategy="skip",
                rule_id=self.rule_id,
                rule_name_ja=self.rule_name_ja,
                action="skip",
                reason_ja=f"年次選択ルール {selected_rule_id} が未登録のため見送り",
                default_strategy=self.default_strategy,
            )
        inner_decision = inner_rule.decide(context)
        return StrategyDecision(
            selected_strategy=inner_decision.selected_strategy,
            rule_id=self.rule_id,
            rule_name_ja=self.rule_name_ja,
            action=inner_decision.action,
            reason_ja=f"[{target_date.year}年選択: {selected_rule_id}] {inner_decision.reason_ja}",
            default_strategy=inner_decision.default_strategy,
            override_strategy=inner_decision.override_strategy,
            matched_filter=inner_decision.matched_filter,
            matched_override=inner_decision.matched_override,
        )
