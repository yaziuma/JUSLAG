from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class StrategyDecision:
    selected_strategy: str
    rule_id: str
    rule_name_ja: str

    action: str
    reason_ja: str

    default_strategy: Optional[str] = None
    override_strategy: Optional[str] = None
    matched_filter: Optional[str] = None
    matched_override: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "selected_strategy": self.selected_strategy,
            "rule_id": self.rule_id,
            "rule_name_ja": self.rule_name_ja,
            "action": self.action,
            "reason_ja": self.reason_ja,
            "default_strategy": self.default_strategy,
            "override_strategy": self.override_strategy,
            "matched_filter": self.matched_filter,
            "matched_override": self.matched_override,
        }
