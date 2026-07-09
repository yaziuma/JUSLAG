from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

TrendRegime = Literal["uptrend", "downtrend", "sideways"]
VolRegime = Literal["high_vol", "mid_vol", "low_vol"]
RotationRegime = Literal["strong_rotation", "mid_rotation", "weak_rotation"]

PrimitiveStrategyId = Literal[
    "curr_oc",
    "gap_ovht_oc",
    "lgap_oc",
    "long_flip_oc",
    "short_only_oc",
    "curr_cc",
    "skip",
]


@dataclass(frozen=True)
class StrategyContext:
    signal_date: str

    candidate_signal_strength: Optional[float]

    open_gap: Optional[float]
    long_gap: Optional[float]
    short_gap: Optional[float]

    trend_regime: Optional[TrendRegime]
    vol_regime: Optional[VolRegime]
    rotation_regime: Optional[RotationRegime]
