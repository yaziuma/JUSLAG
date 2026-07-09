from __future__ import annotations

from dataclasses import asdict

from juslag.report_templates import ReportField, ReportTemplate


def _common_fields() -> list[ReportField]:
    return [
        ReportField("from_date", "date"),
        ReportField("to_date", "date"),
        ReportField("price_mode", "enum", default="raw", options=["raw", "adjusted"]),
        ReportField("fill_policy", "enum", default="strict", options=["strict", "rolling_mean"]),
        ReportField("quantile_q_from", "number", default=0.30),
        ReportField("quantile_q_to", "number", default=0.30),
        ReportField("window_l_from", "number", default=60),
        ReportField("window_l_to", "number", default=60),
        ReportField("min_long_signal_from", "number", default=0.10),
        ReportField("min_long_signal_to", "number", default=0.10),
        ReportField("max_short_signal_from", "number", default=-0.10),
        ReportField("max_short_signal_to", "number", default=-0.10),
        ReportField("min_signal_spread_from", "number", default=0.05),
        ReportField("min_signal_spread_to", "number", default=0.05),
        ReportField("trend_regimes", "enum", default=["uptrend", "sideways", "downtrend"], multiple=True, options=["uptrend", "sideways", "downtrend"]),
        ReportField("vol_regimes", "enum", default=["low_vol", "mid_vol", "high_vol"], multiple=True, options=["low_vol", "mid_vol", "high_vol"]),
        ReportField("rotation_regimes", "enum", default=["weak_rotation", "mid_rotation", "strong_rotation"], multiple=True, options=["weak_rotation", "mid_rotation", "strong_rotation"]),
    ]


def templates() -> list[ReportTemplate]:
    common = _common_fields()
    return [
        ReportTemplate("direction_flip", "方向反転検証レポート", "現行 vs 反転の成績比較", common),
        ReportTemplate("direction_regime", "局面依存方向性レポート", "trend/vol/rotation 別比較", common),
        ReportTemplate("anomaly_days", "異常日分析レポート", "危険日・優位日の抽出", common),
        ReportTemplate("position_filter", "ポジションフィルタ比較レポート", "固定件数と可変件数の比較", common),
        ReportTemplate("signal_spread_history", "シグナルスプレッド履歴レポート", "spread 分布統計と閾値候補", common),
    ]


def template_map() -> dict[str, ReportTemplate]:
    return {t.id: t for t in templates()}


def templates_payload() -> dict[str, object]:
    return {"templates": [{**asdict(t), "fields": [asdict(f) for f in t.fields]} for t in templates()]}
