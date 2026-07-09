from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReportField:
    name: str
    type: str
    required: bool = True
    default: Any = None
    multiple: bool = False
    options: list[str] | None = None


@dataclass(frozen=True)
class ReportTemplate:
    id: str
    label: str
    description: str
    fields: list[ReportField]


@dataclass(frozen=True)
class GeneratedReport:
    template_id: str
    report_title: str
    report_markdown: str
    report_html: str
    conditions: dict[str, Any]
    generated_at: str
    report_path: str | None = None
    report_url: str | None = None


def default_common_conditions() -> dict[str, Any]:
    to_date = date.today()
    from_date = to_date.fromordinal(to_date.toordinal() - 252)
    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "price_mode": "raw",
        "fill_policy": "strict",
        "quantile_q_from": 0.30,
        "quantile_q_to": 0.30,
        "window_l_from": 60,
        "window_l_to": 60,
        "min_long_signal_from": 0.10,
        "min_long_signal_to": 0.10,
        "max_short_signal_from": -0.10,
        "max_short_signal_to": -0.10,
        "min_signal_spread_from": 0.05,
        "min_signal_spread_to": 0.05,
        "trend_regimes": ["uptrend", "sideways", "downtrend"],
        "vol_regimes": ["low_vol", "mid_vol", "high_vol"],
        "rotation_regimes": ["weak_rotation", "mid_rotation", "strong_rotation"],
    }


def render_standard_markdown(template: ReportTemplate, conditions: dict[str, Any], generated_at: str) -> str:
    condition_lines = "\n".join(f"- `{k}`: `{v}`" for k, v in sorted(conditions.items()))
    body = {
        "direction_flip": "現行方向 vs 反転方向を比較し、期間分割・累積・MDD・勝率をサマリ化します。",
        "direction_regime": "trend / vol / rotation の局面別比較と複合局面の所見を整理します。",
        "anomaly_days": "危険日・優位日を抽出し、代表日を深掘りします。",
        "position_filter": "固定件数 vs 可変件数を比較し、LONG/SHORT件数と寄与を示します。",
        "signal_spread_history": "signal spread 分布と p10/p25/p50/p75 を集計し、閾値候補を提示します。",
    }.get(template.id, "テンプレート定義に基づく定型レポートです。")

    return (
        f"# {template.label}\n\n"
        "## 条件メタ情報\n\n"
        f"- 生成日時: `{generated_at}`\n"
        f"- 使用テンプレート: `{template.id}`\n"
        "- 実行バージョン: `standardized-v1`\n"
        f"- 対象期間: `{conditions.get('from_date')}` 〜 `{conditions.get('to_date')}`\n\n"
        "## 条件サマリ\n\n"
        f"{condition_lines}\n\n"
        "## 分析結果サマリ\n\n"
        f"{body}\n\n"
        "## 所見\n\n"
        "- 本実装は初期版（範囲UI + 固定値確定型）です。\n"
        "- `*_from` と `*_to` は将来のグリッド展開に拡張可能です。\n"
    )


def build_report_file_path(base_dir: Path, template_id: str, report_name: str | None, generated_at: datetime) -> Path:
    template_dir = base_dir / template_id
    template_dir.mkdir(parents=True, exist_ok=True)
    file_stem = report_name or f"{template_id}_report_{generated_at.strftime('%Y%m%d_%H%M%S')}"
    if not file_stem.endswith(".md"):
        file_stem = f"{file_stem}.md"
    return template_dir / file_stem
