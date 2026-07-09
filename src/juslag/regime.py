from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TREND_UP_THRESHOLD = 0.03
TREND_DOWN_THRESHOLD = -0.03


@dataclass
class DailyRegimeSnapshot:
    trend_regime: str
    vol_regime: str
    rotation_regime: str
    regime_warning: bool
    regime_warning_reason: list[str]
    regime_warning_message: str


def _classify_trend(cum20_returns: pd.Series) -> pd.Series:
    labels = pd.Series("sideways", index=cum20_returns.index, dtype="object")
    labels[cum20_returns > TREND_UP_THRESHOLD] = "uptrend"
    labels[cum20_returns < TREND_DOWN_THRESHOLD] = "downtrend"
    return labels


def _classify_quantile(
    series: pd.Series,
    *,
    high_pct: float,
    low_pct: float,
    high_label: str,
    low_label: str,
    mid_label: str,
) -> pd.Series:
    clean = series.dropna()
    labels = pd.Series(mid_label, index=series.index, dtype="object")
    if clean.empty:
        return labels

    hi_val = float(np.nanpercentile(clean.values, high_pct))
    lo_val = float(np.nanpercentile(clean.values, low_pct))

    labels[series >= hi_val] = high_label
    labels[series <= lo_val] = low_label
    return labels


def build_regime_frame(jp_cc: pd.DataFrame, signal_df: pd.DataFrame) -> pd.DataFrame:
    jp_proxy = jp_cc.mean(axis=1)
    cum20 = jp_proxy.rolling(20, min_periods=10).sum()
    vol20 = jp_proxy.rolling(20, min_periods=10).std()
    rotation_std = signal_df.std(axis=1)

    trend_regime = _classify_trend(cum20)
    vol_regime = _classify_quantile(
        vol20,
        high_pct=75,
        low_pct=25,
        high_label="high_vol",
        low_label="low_vol",
        mid_label="mid_vol",
    )
    rotation_regime = _classify_quantile(
        rotation_std,
        high_pct=75,
        low_pct=25,
        high_label="strong_rotation",
        low_label="weak_rotation",
        mid_label="mid_rotation",
    )

    return pd.DataFrame(
        {
            "trend_regime": trend_regime,
            "vol_regime": vol_regime,
            "rotation_regime": rotation_regime,
            "cum20_return": cum20,
            "vol20": vol20,
            "rotation_std": rotation_std,
        }
    )


def build_regime_warning(trend_regime: str, vol_regime: str) -> tuple[bool, list[str], str]:
    reasons: list[str] = []
    if trend_regime == "downtrend":
        reasons.append("downtrend")
    if vol_regime == "high_vol":
        reasons.append("high_vol")
    if trend_regime == "downtrend" and vol_regime == "high_vol":
        reasons.append("downtrend_high_vol")

    if not reasons:
        return False, [], "通常局面"

    if "downtrend_high_vol" in reasons:
        message = "注意: downtrend × high_vol 局面では現行方向の信頼性が低下しやすい"
    elif reasons == ["downtrend"]:
        message = "注意: downtrend 局面では現行方向の信頼性が低下しやすい"
    else:
        message = "注意: high_vol 局面では方向判定が不安定になりやすい"

    return True, reasons, message


def snapshot_from_regime_frame(regime_df: pd.DataFrame, date: pd.Timestamp) -> DailyRegimeSnapshot:
    if regime_df.empty or pd.isna(date) or date not in regime_df.index:
        warning, reasons, message = build_regime_warning("sideways", "mid_vol")
        return DailyRegimeSnapshot(
            trend_regime="sideways",
            vol_regime="mid_vol",
            rotation_regime="mid_rotation",
            regime_warning=warning,
            regime_warning_reason=reasons,
            regime_warning_message=message,
        )

    row = regime_df.loc[date]
    trend = str(row.get("trend_regime", "sideways"))
    vol = str(row.get("vol_regime", "mid_vol"))
    rotation = str(row.get("rotation_regime", "mid_rotation"))
    warning, reasons, message = build_regime_warning(trend, vol)
    return DailyRegimeSnapshot(
        trend_regime=trend,
        vol_regime=vol,
        rotation_regime=rotation,
        regime_warning=warning,
        regime_warning_reason=reasons,
        regime_warning_message=message,
    )
