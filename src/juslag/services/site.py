"""data/history.jsonl と data/reports/*.json から閲覧用静的ダッシュボードを生成する。

B-FAD スタック（Bootstrap 5 + Alpine.js、CDN読み込みのみ・ビルド不要）の見た目を踏襲した
ダーク寄りの静的サイトを出力する。全データはHTMLに埋め込み、単体の .json ファイルは出力しない
（サイト全体をHTML単位でパスワード保護してデプロイするため）。
"""
from __future__ import annotations

import html
import json
from pathlib import Path

_CLS_LABELS = {
    "strategy_rule_skip_with_candidates": "戦略ルール見送り（候補あり）",
    "strategy_rule_skip": "戦略ルール見送り",
    "near_miss_threshold": "惜しい（閾値近接）",
    "one_side_only": "片側不足",
    "regime_blocked": "Regime警告",
    "hard_no_signal": "シグナルなし",
}

# no_trade_classification -> Bootstrap badge variant（WebUIの色分けを踏襲）
_CLS_VARIANTS = {
    "strategy_rule_skip_with_candidates": "primary",
    "strategy_rule_skip": "secondary",
    "one_side_only": "secondary",
    "near_miss_threshold": "warning",
    "hard_no_signal": "danger",
    "regime_blocked": "info",
}

# overall_decision / category decision -> Bootstrap badge variant
_DECISION_VARIANTS = {
    "pass": "success",
    "hold": "primary",
    "warn": "warning",
    "reject": "danger",
}

# trend_regime -> レジーム推移ストリップの色
_TREND_COLORS = {
    "uptrend": "#22c55e",
    "downtrend": "#ef4444",
    "range": "#64748b",
    "sideways": "#64748b",
    "neutral": "#64748b",
}

_CATEGORIES: list[tuple[str, str, int]] = [
    ("profitability", "収益性", 30),
    ("stability", "安定性", 25),
    ("cost_resilience", "コスト耐性", 20),
    ("executability", "執行可能性", 10),
    ("data_reliability", "データ信頼性", 15),
]

_BOOTSTRAP_CSS = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
_BOOTSTRAP_JS = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"
_ALPINE_JS = "https://cdn.jsdelivr.net/npm/alpinejs@3.14.9/dist/cdn.min.js"

_FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
    "%3Crect width='16' height='16' rx='3' fill='%232b70ef'/%3E"
    "%3Cpath d='M4 4h2v6c0 1.1.9 2 2 2s2-.9 2-2V4h2v6a4 4 0 1 1-8 0V4z' fill='white'/%3E%3C/svg%3E"
)

_EXTRA_STYLE = """
:root {
  --bg-page: #0d1117;
  --bg-surface: #151b23;
  --bg-raised: #1c2430;
  --text-heading: #f0f3f6;
  --text-default: #c9d1d9;
  --text-muted: #8b949e;
  --border-default: #30363d;
  --accent: #58a6ff;
  --positive: #3fb950;
  --negative: #f85149;
  --warning: #d29922;
}
body {
  background: var(--bg-page);
  color: var(--text-default);
  font-family: -apple-system, "Segoe UI", "Hiragino Sans", "Noto Sans JP", sans-serif;
  font-size: 14px;
  letter-spacing: 0;
}
[x-cloak] { display: none !important; }
.app-shell { max-width: 1180px; margin: 0 auto; padding: 0 20px; }
.navbar { background: rgba(13,17,23,.96); border-bottom: 1px solid var(--border-default) !important; }
.navbar-brand { font-size: 15px; letter-spacing: 0; }
.surface-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 8px;
}
.text-heading { color: var(--text-heading); }
.text-muted-soft { color: var(--text-muted); }
a { color: var(--accent); }
.table { color: var(--text-default); }
.table > :not(caption) > * > * { border-color: var(--border-default); }
.section-label { color: var(--text-muted); font-size: 11px; font-weight: 700; text-transform: uppercase; }
.dashboard-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border-default); }
.dashboard-tab {
  border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--text-muted);
  min-width: 88px; padding: 12px 16px 10px; font-weight: 600;
}
.dashboard-tab:hover { color: var(--text-heading); }
.dashboard-tab.active { color: var(--text-heading); border-bottom-color: var(--accent); }
.decision-band { border-left: 4px solid var(--warning); }
.decision-band.execute { border-left-color: var(--positive); }
.decision-band.blocked { border-left-color: var(--negative); }
.decision-word { font-size: 28px; font-weight: 750; line-height: 1; color: var(--text-heading); }
.metric-value { color: var(--text-heading); font-size: 22px; font-weight: 700; line-height: 1.1; }
.regime-list { display: flex; flex-wrap: wrap; gap: 8px; }
.regime-pill { background: var(--bg-raised); border: 1px solid var(--border-default); border-radius: 999px; padding: 5px 10px; }
.plan-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: var(--border-default); border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; }
.plan-column { background: var(--bg-surface); padding: 18px; min-width: 0; }
.plan-list { display: grid; gap: 8px; }
.plan-item { display: flex; justify-content: space-between; gap: 12px; padding-top: 8px; border-top: 1px solid var(--border-default); }
.plan-item:first-child { border-top: 0; padding-top: 0; }
.plan-long { color: #56d364; }
.plan-short { color: #ff7b72; }
.explain-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--border-default); border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; }
.explain-panel { background: var(--bg-surface); padding: 18px; }
.fact-list { display: grid; gap: 9px; }
.fact-row { display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--border-default); padding-bottom: 8px; }
.fact-row:last-child { border-bottom: 0; padding-bottom: 0; }
.order-list { border-top: 1px solid var(--border-default); }
.order-row { display: grid; grid-template-columns: 90px minmax(170px, 1fr) 80px 110px 110px; gap: 14px; align-items: center; padding: 12px 0; border-bottom: 1px solid var(--border-default); }
.order-side { font-size: 12px; font-weight: 750; }
.warning-note { background: rgba(210,153,34,.08); border-left: 3px solid var(--warning); padding: 10px 12px; }
.history-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) auto; gap: 12px; }
.history-search { background: var(--bg-surface); border-color: var(--border-default); color: var(--text-heading); }
.history-search:focus { background: var(--bg-surface); color: var(--text-heading); border-color: var(--accent); box-shadow: none; }
.history-list { border-top: 1px solid var(--border-default); }
.history-row { display: grid; grid-template-columns: 105px 140px minmax(160px, 1fr) 92px 28px; gap: 16px; align-items: center; padding: 13px 4px; border-bottom: 1px solid var(--border-default); color: inherit; text-decoration: none; }
.history-row:hover { background: rgba(255,255,255,.025); color: inherit; }
.history-date { color: var(--text-heading); font-variant-numeric: tabular-nums; font-weight: 650; }
.history-plan { min-width: 0; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 7px; background: var(--warning); }
.status-dot.execute { background: var(--positive); }
.score-track { height: 6px; background: var(--bg-raised); border-radius: 3px; overflow: hidden; }
.score-fill { height: 100%; background: var(--accent); }
.analysis-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.trend-list { display: grid; gap: 10px; }
.trend-row { display: grid; grid-template-columns: 88px 1fr 36px; align-items: center; gap: 10px; }
.summary-viewport { max-height: 320px; overflow: auto; padding-right: 8px; scrollbar-color: var(--border-default) transparent; }
pre.summary {
  white-space: pre-wrap; background: transparent; border: 0; margin: 0;
  padding: 0; font-family: inherit; font-size: 14px; line-height: 1.7; color: var(--text-default);
}
pre.raw {
  background: rgba(255,255,255,.03); border: 1px solid var(--border-default); overflow-x: auto;
  padding: 12px; font-size: .75rem; color: var(--text-default);
}
details > summary { cursor: pointer; margin: 8px 0; color: var(--text-muted); }
.regime-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(8px, 1fr)); gap: 3px; }
.regime-cell { width: 100%; height: 34px; border-radius: 2px; }
.btn-group .btn.active { color: #fff; }
@media (max-width: 767px) {
  body { font-size: 14px; }
  .app-shell { padding: 0 14px; }
  .dashboard-tab { min-width: 0; flex: 1; padding-inline: 8px; }
  .decision-word { font-size: 24px; }
  .plan-grid, .analysis-grid, .explain-grid { grid-template-columns: 1fr; }
  .history-toolbar { grid-template-columns: 1fr; }
  .history-row { grid-template-columns: 92px 1fr 24px; gap: 10px; }
  .history-row .history-plan, .history-row .history-regime { display: none; }
  .metric-value { font-size: 19px; }
  .surface-card { border-radius: 6px; }
  .order-row { grid-template-columns: 74px 1fr auto; gap: 8px; }
  .order-row .order-price, .order-row .order-method { display: none; }
}
"""


def load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def load_reports(reports_dir: Path) -> list[dict]:
    if not reports_dir.exists():
        return []
    reports: list[dict] = []
    for p in sorted(reports_dir.glob("*.json")):
        try:
            reports.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return reports


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def _json_embed(data: object) -> str:
    """<script> に安全に埋め込めるJSON文字列（</script>対策込み）。"""
    return json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")


def _rotation_regime(ds: dict) -> str | None:
    return (ds.get("strategy_context") or {}).get("rotation_regime") or ds.get("rotation_regime")


def _cls_label(cls: str | None) -> str:
    return _CLS_LABELS.get(cls or "", cls or "-")


def _cls_variant(cls: str | None) -> str:
    return _CLS_VARIANTS.get(cls or "", "secondary")


def _decision_variant(decision: str | None) -> str:
    return _DECISION_VARIANTS.get(decision or "", "secondary")


def _final_actionable(report: dict) -> bool:
    ds = report.get("daily_signal") or {}
    judge = (report.get("backtest") or {}).get("judge") or {}
    return bool(ds.get("tradeable")) and judge.get("overall_decision") == "pass"


def _money(value: object) -> str:
    return f"¥{value:,.0f}" if isinstance(value, (int, float)) else "-"


def _percent(value: object, digits: int = 2) -> str:
    return f"{value:.{digits}f}%" if isinstance(value, (int, float)) else "-"


def _plan_summary(entries: list[dict] | None) -> str:
    if not entries:
        return "-"
    parts = []
    for e in entries:
        sector = e.get("sector") or e.get("ticker") or ""
        weight = e.get("weight")
        if isinstance(weight, (int, float)):
            parts.append(f"{sector}（{weight:g}%）")
        else:
            parts.append(str(sector))
    return " / ".join(parts)


def _page(title: str, body: str, home_href: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="ja" data-bs-theme="dark"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<link rel="icon" href="{_FAVICON}">\n'
        f'<title>{_esc(title)}</title>\n'
        f'<link href="{_BOOTSTRAP_CSS}" rel="stylesheet">\n'
        f'<script defer src="{_ALPINE_JS}"></script>\n'
        f'<script src="{_BOOTSTRAP_JS}"></script>\n'
        f"<style>{_EXTRA_STYLE}</style>\n"
        "</head><body>\n"
        '<nav class="navbar sticky-top">\n'
        '  <div class="app-shell w-100 py-2 d-flex justify-content-between align-items-center">\n'
        f'    <a class="navbar-brand mb-0 h1 fw-semibold text-heading text-decoration-none" href="{_esc(home_href)}">'
        "JUSLAG 日次リサーチ</a>\n"
        "  </div>\n"
        "</nav>\n"
        f'<main class="app-shell py-3">\n{body}\n</main>\n'
        "</body></html>\n"
    )


def _index_rows(reports: list[dict]) -> list[dict]:
    rows = []
    for r in sorted(reports, key=lambda r: r.get("date") or "", reverse=True):
        date = r.get("date")
        ds = r.get("daily_signal") or {}
        judge = (r.get("backtest") or {}).get("judge") or {}
        plan = ds.get("execution_plan") or {}
        tradeable = bool(ds.get("tradeable"))
        final_actionable = _final_actionable(r)
        cls = ds.get("no_trade_classification")
        rows.append(
            {
                "date": date,
                "href": f"reports/{date}.html",
                "tradeable": tradeable,
                "final_actionable": final_actionable,
                "classification_label": _cls_label(cls) if not tradeable else "",
                "classification_variant": _cls_variant(cls),
                "trend_regime": ds.get("trend_regime"),
                "vol_regime": ds.get("vol_regime"),
                "rotation_regime": _rotation_regime(ds),
                "long": _plan_summary(plan.get("long")),
                "short": _plan_summary(plan.get("short")),
                "judge_score": judge.get("overall_score"),
                "judge_decision": judge.get("overall_decision"),
                "judge_summary": judge.get("summary"),
            }
        )
    return rows


def _regime_strip(reports: list[dict]) -> str:
    ordered = sorted(reports, key=lambda r: r.get("date") or "")
    if not ordered:
        return '<p class="small text-muted-soft mb-0">レジームデータがありません。</p>'
    cells = []
    for r in ordered:
        ds = r.get("daily_signal") or {}
        trend = ds.get("trend_regime")
        vol = ds.get("vol_regime")
        rotation = _rotation_regime(ds)
        color = _TREND_COLORS.get(trend or "", "#334155")
        title = f"{r.get('date', '')}  trend={trend or '-'} vol={vol or '-'} rotation={rotation or '-'}"
        cells.append(f'<div class="regime-cell" style="background:{color};" title="{_esc(title)}"></div>')
    return f'<div class="regime-strip">{"".join(cells)}</div>'


def _backtest_comparison(report: dict) -> str:
    comparison = report.get("backtest_comparison") or {}
    current = comparison.get("current") or {}
    paper = comparison.get("paper_aligned") or {}
    if not current or not paper:
        return ""

    def _cell(entry: dict, key: str, *, percent: bool = False) -> str:
        value = (entry.get("metrics") or {}).get(key)
        return _percent(value) if percent else _esc(value if value is not None else "-")

    def _judge(entry: dict) -> str:
        judge = entry.get("judge") or {}
        decision = str(judge.get("overall_decision") or "-").upper()
        score = judge.get("overall_score")
        return f"{_esc(decision)} / {_esc(score if score is not None else '-')}点"

    shared = comparison.get("shared_cost_assumptions") or {}
    rows = [
        ("戦略", current.get("strategy_name"), paper.get("strategy_name")),
        ("価格系列", current.get("price_mode"), paper.get("price_mode")),
        ("論文外ルール", current.get("strategy_rule_id") or "なし", paper.get("strategy_rule_id") or "なし"),
        ("Gross 年率", _cell(current, "gross_ar_pct", percent=True), _cell(paper, "gross_ar_pct", percent=True)),
        ("コスト後年率", _cell(current, "net_pre_tax_ar_pct", percent=True), _cell(paper, "net_pre_tax_ar_pct", percent=True)),
        ("税引後年率", _cell(current, "net_after_tax_ar_pct", percent=True), _cell(paper, "net_after_tax_ar_pct", percent=True)),
        ("税引後 R/R", _cell(current, "net_after_tax_rr"), _cell(paper, "net_after_tax_rr")),
        ("税引後 MDD", _cell(current, "net_after_tax_mdd_pct", percent=True), _cell(paper, "net_after_tax_mdd_pct", percent=True)),
        ("コスト低下幅", _cell(current, "cost_drag_pct", percent=True), _cell(paper, "cost_drag_pct", percent=True)),
        ("Judge", _judge(current), _judge(paper)),
    ]
    body = "".join(
        f"<tr><th>{_esc(label)}</th><td>{left}</td><td>{right}</td></tr>"
        for label, left, right in rows
    )
    costs = (
        f"片道手数料 {_esc(shared.get('commission_bps_per_side'))}bps / "
        f"片道スリッページ {_esc(shared.get('slippage_bps_per_side'))}bps / "
        f"年率借株料 {_percent((shared.get('short_borrow_rate_annual') or 0) * 100)} / "
        f"税率 {_percent((shared.get('tax_rate') or 0) * 100)}"
    )
    return (
        '<div class="surface-card p-3 p-md-4 mb-3">'
        '<div class="section-label mb-1">Backtest comparison</div>'
        '<h2 class="h6 text-heading mb-2">論文準拠 vs 現行運用</h2>'
        '<p class="small text-muted-soft mb-3">論文準拠は調整済み価格・PCA SUB単体・上下30%等ウェイト。'
        '掲載値の転載ではなく、現行と同じ期間・コスト実装で再計算した比較です。</p>'
        '<div class="table-responsive"><table class="table table-sm align-middle mb-2">'
        '<thead><tr><th>比較項目</th><th>現行運用</th><th>論文準拠</th></tr></thead>'
        f'<tbody>{body}</tbody></table></div>'
        f'<p class="small text-muted-soft mb-0">共通コスト設定: {costs}</p>'
        '</div>'
    )


def _render_index(history: list[dict], reports: list[dict]) -> str:
    rows = _index_rows(reports)
    latest_report = max(reports, key=lambda r: r.get("date") or "") if reports else {}
    latest_ds = latest_report.get("daily_signal") or {}
    latest_judge = (latest_report.get("backtest") or {}).get("judge") or {}
    latest_plan = latest_ds.get("execution_plan") or {}
    latest_history = history[-1] if history else {}
    tradeable = bool(latest_ds.get("tradeable"))
    final_actionable = _final_actionable(latest_report)
    judge_decision = latest_judge.get("overall_decision")
    decision_text = "発注候補" if final_actionable else "見送り"
    decision_class = "execute" if final_actionable else "blocked"
    if not tradeable:
        decision_reason = _cls_label(latest_ds.get("no_trade_classification"))
    elif judge_decision == "reject":
        decision_reason = "注文候補は生成済み / モデル審査で却下"
    elif judge_decision == "pass":
        decision_reason = "シグナル条件・モデル審査ともに通過"
    else:
        decision_reason = "注文候補は生成済み / モデル審査は要確認"
    score = latest_judge.get("overall_score")
    score_pct = max(0, min(100, score)) if isinstance(score, (int, float)) else 0
    backtest = latest_report.get("backtest") or {}
    judge_strategy_name = backtest.get("judge_strategy_name") or "PCA SUB"
    params = backtest.get("params") or {}
    metrics = latest_judge.get("metrics_snapshot") or {}
    strategy = latest_ds.get("strategy_decision") or {}
    context = latest_ds.get("strategy_context") or {}
    comparison_html = _backtest_comparison(latest_report)

    def order_items(entries: list[dict] | None, side: str) -> str:
        if not entries:
            return ""
        items = []
        for entry in entries:
            is_long = side == "long"
            side_label = "現物買い" if is_long else "信用新規売り"
            side_class = "plan-long" if is_long else "plan-short"
            lots = entry.get("normalized_lots")
            lots_text = f"{lots:,}口" if isinstance(lots, int) else "-"
            items.append(
                '<div class="order-row">'
                f'<div class="order-side {side_class}">{side_label}</div>'
                f'<div><strong class="text-heading">{_esc(entry.get("ticker") or "-")} '
                f'{_esc(entry.get("sector") or "-")}</strong></div>'
                f'<strong>{lots_text}</strong>'
                f'<div class="order-price text-end">{_money(entry.get("normalized_purchase_jpy"))}</div>'
                '<div class="order-method text-end text-muted-soft">寄成・当日</div></div>'
            )
        return "".join(items)

    orders_html = order_items(latest_plan.get("long"), "long") + order_items(
        latest_plan.get("short"), "short"
    )
    candidate_quantity = sum(
        entry.get("normalized_lots") or 0
        for entry in (latest_plan.get("long") or []) + (latest_plan.get("short") or [])
    )
    if final_actionable:
        order_gate_html = (
            f"<strong>発注候補: 合計{candidate_quantity:,}口</strong><br>"
            '<span class="small">モデル審査まで通過。執行前チェック後に注文します。</span>'
        )
    else:
        order_gate_html = (
            "<strong>本日の発注数量: 0口</strong><br>"
            f'<span class="small">{_esc(decision_reason)}のため、以下は発注しない参考値です。</span>'
        )

    data_json = _json_embed({"rows": rows})
    summary = latest_history.get("summary") or latest_report.get("slack_fallback_text") or "サマリーはありません。"
    report_href = f'reports/{_esc(latest_report.get("date"))}.html' if latest_report else "#"

    body = f"""
<script>window.__DATA__ = {data_json};</script>
<script>
function dashboard() {{
  return {{
    tab: 'today', filter: 'all', query: '', visibleCount: 20,
    rows: (window.__DATA__ && window.__DATA__.rows) || [],
    get filteredRows() {{
      const q = this.query.trim().toLowerCase();
      return this.rows.filter((row) => {{
        const matchesFilter = this.filter === 'all' ||
          (this.filter === 'executed' && row.tradeable) ||
          (this.filter === 'skipped' && !row.tradeable);
        const haystack = [row.date, row.long, row.short, row.trend_regime,
          row.vol_regime, row.rotation_regime].join(' ').toLowerCase();
        return matchesFilter && (!q || haystack.includes(q));
      }});
    }},
    get displayedRows() {{
      return this.filteredRows.slice(0, this.visibleCount);
    }}
  }};
}}
</script>
<div x-data="dashboard()">
  <div class="d-flex justify-content-between align-items-end gap-3 mb-2">
    <div>
      <div class="section-label mb-1">Operations dashboard</div>
      <h1 class="h4 text-heading mb-0">日次リサーチ</h1>
    </div>
    <div class="text-end small text-muted-soft">
      <div>最終更新</div><strong class="text-heading">{_esc(latest_report.get("date") or "-")}</strong>
    </div>
  </div>

  <div class="dashboard-tabs mb-4" role="tablist">
    <button class="dashboard-tab" :class="{{active: tab === 'today'}}" @click="tab = 'today'">本日</button>
    <button class="dashboard-tab" :class="{{active: tab === 'history'}}" @click="tab = 'history'">履歴</button>
    <button class="dashboard-tab" :class="{{active: tab === 'analysis'}}" @click="tab = 'analysis'">分析</button>
  </div>

  <section x-show="tab === 'today'" x-cloak>
    <div class="surface-card decision-band {decision_class} p-3 p-md-4 mb-3">
      <div class="row align-items-center g-3">
        <div class="col-md-5">
          <div class="section-label mb-2">最終運用判断</div>
          <div class="d-flex align-items-center gap-3">
            <div class="decision-word">{decision_text}</div>
            <span class="text-muted-soft">{_esc(decision_reason)}</span>
          </div>
        </div>
        <div class="col-6 col-md-2">
          <div class="section-label mb-1">Judge</div>
          <div class="metric-value">{_esc(score if score is not None else "-")}<small class="fs-6 text-muted-soft"> / 100</small></div>
        </div>
        <div class="col-6 col-md-2">
          <div class="section-label mb-1">モデル審査</div>
          <div class="metric-value fs-5">{_esc((judge_decision or "-").upper())}</div>
        </div>
        <div class="col-md-3 text-md-end">
          <a class="btn btn-sm btn-outline-light" href="{report_href}">詳細レポート</a>
        </div>
      </div>
    </div>

    <div class="explain-grid mb-3">
      <div class="explain-panel">
        <div class="section-label mb-3">1. モデル作成条件</div>
        <div class="fact-list small">
          <div class="fact-row"><span class="text-muted-soft">モデル</span><strong>部分空間正則化PCA</strong></div>
          <div class="fact-row"><span class="text-muted-soft">標本期間</span><strong>{_esc(params.get("sample_start") or "-")} ～ { _esc(params.get("sample_end") or "-")}</strong></div>
          <div class="fact-row"><span class="text-muted-soft">学習窓</span><strong>{_esc(params.get("window_l") or "-")}営業日</strong></div>
          <div class="fact-row"><span class="text-muted-soft">因子数 / 正則化</span><strong>{_esc(params.get("k_factors") or "-")} / {_esc(params.get("lambda_reg") or "-")}</strong></div>
          <div class="fact-row"><span class="text-muted-soft">選別</span><strong>上下{_percent((params.get("quantile_q") or 0) * 100, 0)}</strong></div>
        </div>
      </div>
      <div class="explain-panel">
        <div class="section-label mb-3">2. 当日シグナル判定</div>
        <div class="fact-list small">
          <div class="fact-row"><span class="text-muted-soft">適用ルール</span><strong>{_esc(strategy.get("rule_id") or "-")}</strong></div>
          <div class="fact-row"><span class="text-muted-soft">寄りgap</span><strong>{_percent((context.get("open_gap") or 0) * 100)} / 上限1.50%</strong></div>
          <div class="fact-row"><span class="text-muted-soft">Rotation</span><strong>{_esc(context.get("rotation_regime") or "-")} / weak以外</strong></div>
          <div class="fact-row"><span class="text-muted-soft">ルール結果</span><strong>{_esc((strategy.get("action") or "-").upper())}</strong></div>
          <div class="fact-row"><span class="text-muted-soft">対象日</span><strong>{_esc(latest_ds.get("execution_target_jp_date") or "-")}</strong></div>
        </div>
      </div>
      <div class="explain-panel">
        <div class="section-label mb-3">3. モデル審査基準</div>
        <div class="fact-list small">
          <div class="fact-row"><span class="text-muted-soft">審査対象</span><strong>{_esc(judge_strategy_name)}</strong></div>
          <div class="fact-row"><span class="text-muted-soft">税引後年率 ≥ 3%</span><strong>{_percent(metrics.get("net_after_tax_ar_pct"))}</strong></div>
          <div class="fact-row"><span class="text-muted-soft">R/R ≥ 0.30</span><strong>{_esc(metrics.get("net_after_tax_rr") if metrics.get("net_after_tax_rr") is not None else "-")}</strong></div>
          <div class="fact-row"><span class="text-muted-soft">MDD ≥ -25%</span><strong>{_percent(metrics.get("net_after_tax_mdd_pct"))}</strong></div>
          <div class="fact-row"><span class="text-muted-soft">コスト低下幅 &lt; 3%</span><strong>{_percent(metrics.get("cost_drag_pct"))}</strong></div>
          <div class="fact-row"><span class="text-muted-soft">審査結果</span><strong>{_esc((judge_decision or "-").upper())}</strong></div>
        </div>
      </div>
    </div>

    <div class="surface-card p-3 p-md-4 mb-3">
      <div class="d-flex justify-content-between align-items-end mb-3 gap-3">
        <div><div class="section-label mb-1">参考注文案</div><h2 class="h6 text-heading mb-0">Judgeゲート前のシグナル注文</h2></div>
        <span class="text-muted-soft small">基準価格ベース</span>
      </div>
      <div class="warning-note mb-3">{order_gate_html}</div>
      <div class="order-list">{orders_html or '<p class="text-muted-soft py-3 mb-0">注文候補はありません。</p>'}</div>
      <p class="small text-muted-soft mt-3 mb-0">数量は均等化した参考口数、金額は直近価格 × 口数の概算です。実注文前に売買単位、価格、信用売建可否、余力を証券会社画面で確認してください。</p>
    </div>

    <div class="surface-card p-3 p-md-4">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <div class="section-label">Latest summary</div>
        <span class="small text-muted-soft">LLM: {_esc(latest_history.get("llm_status") or "-")}</span>
      </div>
      <div class="summary-viewport"><pre class="summary">{_esc(summary)}</pre></div>
    </div>
  </section>

  <section x-show="tab === 'history'" x-cloak>
    <div class="history-toolbar mb-3">
      <input class="form-control form-control-sm history-search" x-model="query" placeholder="日付・銘柄・レジームで検索" aria-label="履歴検索">
      <div class="btn-group btn-group-sm" role="group" aria-label="判定フィルタ">
        <button class="btn btn-outline-secondary" :class="{{active: filter === 'all'}}" @click="filter = 'all'">全て</button>
        <button class="btn btn-outline-secondary" :class="{{active: filter === 'executed'}}" @click="filter = 'executed'">候補あり</button>
        <button class="btn btn-outline-secondary" :class="{{active: filter === 'skipped'}}" @click="filter = 'skipped'">候補なし</button>
      </div>
    </div>
    <div class="history-list">
      <template x-for="row in displayedRows" :key="row.date">
        <a class="history-row" :href="row.href">
          <div class="history-date" x-text="row.date"></div>
          <div><span class="status-dot" :class="{{execute: row.tradeable}}"></span><span x-text="row.tradeable ? '候補あり' : '候補なし'"></span><div class="small text-muted-soft" x-text="'Judge ' + (row.judge_decision || '-')"></div></div>
          <div class="history-plan" x-text="'L: ' + (row.long || '-') + '  /  S: ' + (row.short || '-')"></div>
          <div class="history-regime text-muted-soft" x-text="row.trend_regime || '-'"></div>
          <div class="text-end text-muted-soft">›</div>
        </a>
      </template>
    </div>
    <p class="text-muted-soft py-4" x-show="filteredRows.length === 0">該当する履歴はありません。</p>
    <div class="text-center py-3" x-show="displayedRows.length < filteredRows.length">
      <button class="btn btn-sm btn-outline-secondary" @click="visibleCount += 20">さらに表示</button>
    </div>
  </section>

  <section x-show="tab === 'analysis'" x-cloak>
    {comparison_html}
    <div class="analysis-grid mb-3">
      <div class="surface-card p-3 p-md-4">
        <div class="section-label mb-3">Judge score trend</div>
        <div class="trend-list">
          <template x-for="row in rows.slice(0, 12)" :key="row.date">
            <div class="trend-row">
              <span class="small" x-text="row.date.slice(5)"></span>
              <div class="score-track"><div class="score-fill" :style="'width:' + (row.judge_score || 0) + '%'"></div></div>
              <strong class="text-end" x-text="row.judge_score == null ? '-' : row.judge_score"></strong>
            </div>
          </template>
        </div>
      </div>
      <div class="surface-card p-3 p-md-4">
        <div class="section-label mb-3">Current assessment</div>
        <div class="metric-value mb-3">{_esc(score if score is not None else "-")} / 100</div>
        <div class="score-track mb-3"><div class="score-fill" style="width:{score_pct}%"></div></div>
        <p class="mb-0">{_esc(latest_judge.get("summary") or "判定情報はありません。")}</p>
      </div>
    </div>
    <div class="surface-card p-3 p-md-4">
      <div class="section-label mb-2">Regime timeline</div>
      <p class="small text-muted-soft mb-3">緑: 上昇 / 赤: 下落 / グレー: レンジ・不明</p>
      {_regime_strip(reports)}
    </div>
  </section>
</div>
"""

    return _page("JUSLAG 日次リサーチ", body, "index.html")


def _summary_table(report: dict) -> str:
    ds = report.get("daily_signal") or {}
    plan = ds.get("execution_plan") or {}
    tradeable = bool(ds.get("tradeable"))
    cls = ds.get("no_trade_classification")
    decision = ds.get("strategy_decision") or {}
    rotation = _rotation_regime(ds)

    if tradeable:
        exec_cell = '<span class="badge text-bg-success">執行</span>'
    else:
        reason = ds.get("trade_block_reason")
        exec_cell = (
            '<span class="badge text-bg-warning">見送り</span> '
            f'<span class="text-muted-soft small">({_esc(reason) or "-"})</span>'
        )

    rows: list[tuple[str, str]] = [
        ("執行対象日 (JP)", _esc(ds.get("execution_target_jp_date")) or "-"),
        ("参照日 (US)", _esc(ds.get("signal_reference_us_date")) or "-"),
        ("執行可否", exec_cell),
        (
            "見送り分類",
            f'<span class="badge text-bg-{_cls_variant(cls)}">{_esc(_cls_label(cls))}</span>'
            if not tradeable and cls
            else "-",
        ),
        (
            "レジーム",
            f'<span class="badge text-bg-light me-1">trend: {_esc(ds.get("trend_regime")) or "-"}</span>'
            f'<span class="badge text-bg-light me-1">vol: {_esc(ds.get("vol_regime")) or "-"}</span>'
            f'<span class="badge text-bg-light">rotation: {_esc(rotation) or "-"}</span>',
        ),
        ("LONG", _esc(_plan_summary(plan.get("long")))),
        ("SHORT", _esc(_plan_summary(plan.get("short")))),
    ]
    if decision:
        action = decision.get("action")
        rule_label = decision.get("rule_name_ja") or decision.get("rule_id") or "-"
        rows.append(
            (
                "戦略ルール",
                f'{_esc(rule_label)} <span class="badge text-bg-{"success" if action == "execute" else "secondary"} ms-1">'
                f"{_esc(action) or '-'}</span>",
            )
        )
        rows.append(("ルール判定理由", _esc(decision.get("reason_ja")) or "-"))
        if decision.get("matched_filter"):
            rows.append(("マッチしたフィルタ", f"<code>{_esc(decision.get('matched_filter'))}</code>"))

    rows_html = "\n".join(f"<tr><th>{_esc(k)}</th><td>{v}</td></tr>" for k, v in rows)
    return f'<table class="table table-sm mb-0"><tbody>\n{rows_html}\n</tbody></table>'


def _judge_card(judge: dict) -> str:
    if not judge:
        return ""
    overall_decision = judge.get("overall_decision")
    parts = [
        '<div class="surface-card p-4 mb-4">\n',
        '  <div class="d-flex align-items-center gap-3 mb-3 flex-wrap">\n',
        '    <h2 class="h5 text-heading mb-0">バックテスト Judge</h2>\n',
        f'    <span class="badge fs-6 px-3 py-2 text-bg-{_decision_variant(overall_decision)}">'
        f'{_esc((overall_decision or "-").upper())}</span>\n',
        f'    <span class="fw-semibold">{_esc(judge.get("overall_score"))} / 100 点</span>\n',
        "  </div>\n",
    ]
    if judge.get("summary"):
        parts.append(f'  <p class="small mb-3">{_esc(judge.get("summary"))}</p>\n')

    category_scores = judge.get("category_scores") or {}
    category_decisions = judge.get("category_decisions") or {}
    parts.append('  <div class="row g-3 mb-3">\n')
    for key, label, max_pts in _CATEGORIES:
        score = category_scores.get(key)
        decision = category_decisions.get(key)
        pct = (score / max_pts * 100.0) if isinstance(score, (int, float)) and max_pts else 0.0
        pct = max(0.0, min(100.0, pct))
        variant = _decision_variant(decision)
        parts.append(
            '    <div class="col-md-4 col-6">\n'
            f'      <div class="d-flex justify-content-between small mb-1"><span>{_esc(label)}</span>'
            f'<span>{_esc(score if score is not None else "-")} / {max_pts}'
            f'（{_esc(decision) or "-"}）</span></div>\n'
            f'      <div class="progress" style="height:10px;">'
            f'<div class="progress-bar bg-{variant}" style="width:{pct:.1f}%"></div></div>\n'
            "    </div>\n"
        )
    parts.append("  </div>\n")

    actions = judge.get("actions") or []
    if actions:
        parts.append('  <div class="mb-3">\n    <div class="fw-semibold small mb-1">推奨アクション</div>\n')
        parts.append('    <ul class="mb-0 small ps-3">\n')
        for a in actions:
            parts.append(f"      <li>{_esc(a)}</li>\n")
        parts.append("    </ul>\n  </div>\n")

    reasons = judge.get("reasons") or []
    if reasons:
        parts.append(
            f'  <details>\n    <summary class="small">判定理由（{len(reasons)}件）</summary>\n    <div class="mt-2">\n'
        )
        for r in reasons:
            severity = r.get("severity")
            variant = "danger" if severity == "reject" else ("warning" if severity == "warn" else "secondary")
            parts.append(
                '      <div class="d-flex align-items-start gap-2 mb-1 small">\n'
                f'        <span class="badge text-bg-{variant} flex-shrink-0">{_esc(severity)}</span>\n'
                f'        <span><code>{_esc(r.get("code"))}</code> — {_esc(r.get("message"))}</span>\n'
                "      </div>\n"
            )
        parts.append("    </div>\n  </details>\n")

    parts.append("</div>\n")
    return "".join(parts)


def _candidate_table(candidates: list[dict] | None, threshold_label: str) -> str:
    candidates = candidates or []
    if not candidates:
        return '<p class="small text-muted-soft">候補データがありません。</p>'
    rows = []
    for c in candidates:
        signal = c.get("signal")
        signal_str = f"{signal:+.4f}" if isinstance(signal, (int, float)) else "-"
        gap = c.get("gap_to_threshold")
        gap_str = f"{gap:+.4f}" if isinstance(gap, (int, float)) else "-"
        passes = c.get("passes")
        cls = "text-success" if passes else "text-danger"
        rows.append(
            "<tr>"
            f'<td><code>{_esc(c.get("ticker"))}</code></td>'
            f'<td class="text-muted-soft">{_esc(c.get("sector"))}</td>'
            f'<td class="text-end {cls}">{signal_str}</td>'
            f'<td class="text-end text-muted-soft">差: {gap_str}</td>'
            "</tr>"
        )
    return (
        f'<p class="small text-muted-soft mb-1">{_esc(threshold_label)}</p>'
        '<table class="table table-sm table-borderless mb-0"><tbody>\n' + "\n".join(rows) + "\n</tbody></table>"
    )


def _candidate_signal_stats_card(ds: dict) -> str:
    stats = ds.get("candidate_signal_stats") or {}
    if not stats:
        return ""
    long_threshold = stats.get("long_threshold")
    short_threshold = stats.get("short_threshold")
    return (
        '<div class="surface-card p-4 mb-4">\n'
        '  <h2 class="h5 text-heading mb-3">候補シグナル詳細</h2>\n'
        '  <div class="row g-3">\n'
        f'    <div class="col-md-6">'
        f'{_candidate_table(stats.get("top_long_candidates"), f"LONG候補上位（閾値: ≥{long_threshold}）")}</div>\n'
        f'    <div class="col-md-6">'
        f'{_candidate_table(stats.get("top_short_candidates"), f"SHORT候補下位（閾値: ≤{short_threshold}）")}</div>\n'
        "  </div>\n"
        "</div>\n"
    )


def _signal_rows_table(ds: dict) -> str:
    rows = ds.get("rows") or []
    if not rows:
        return ""
    trs = []
    for row in rows:
        signal = row.get("signal")
        signal_str = f"{signal:+.4f}" if isinstance(signal, (int, float)) else "-"
        position = row.get("position") or "-"
        variant = "success" if position == "LONG" else ("danger" if position == "SHORT" else "secondary")
        trs.append(
            "<tr>"
            f'<td><code>{_esc(row.get("ticker"))}</code></td>'
            f"<td>{_esc(row.get('sector'))}</td>"
            f'<td class="text-end">{signal_str}</td>'
            f'<td><span class="badge text-bg-{variant}">{_esc(position)}</span></td>'
            "</tr>"
        )
    return (
        '<div class="surface-card p-4 mb-4">\n'
        '  <h2 class="h5 text-heading mb-3">セクター別シグナル</h2>\n'
        '  <div class="table-responsive" style="max-height:420px;">\n'
        '    <table class="table table-sm table-hover mb-0">\n'
        "      <thead><tr><th>銘柄コード</th><th>セクター</th><th>シグナル値</th><th>推奨ポジション</th></tr></thead>\n"
        f"      <tbody>\n{''.join(trs)}\n      </tbody>\n"
        "    </table>\n  </div>\n</div>\n"
    )


def _render_report_page(report: dict) -> str:
    date = report.get("date", "")
    ds = report.get("daily_signal") or {}
    judge = (report.get("backtest") or {}).get("judge") or {}

    parts: list[str] = [
        '<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">\n'
        f'  <h1 class="h4 text-heading mb-0">日次レポート {_esc(date)}</h1>\n'
        '  <a class="small" href="../index.html">← 一覧へ戻る</a>\n'
        "</div>\n"
    ]

    parts.append(
        '<div class="surface-card p-4 mb-4">\n'
        '  <h2 class="h5 text-heading mb-3">シグナル判定</h2>\n'
        f"  {_summary_table(report)}\n"
        "</div>\n"
    )

    parts.append(_judge_card(judge))
    parts.append(_backtest_comparison(report))
    parts.append(_candidate_signal_stats_card(ds))
    parts.append(_signal_rows_table(ds))

    fallback = report.get("slack_fallback_text")
    if fallback:
        parts.append(
            '<div class="surface-card p-4 mb-4">\n'
            '  <h2 class="h5 text-heading mb-3">Slack文面</h2>\n'
            f'  <pre class="summary mb-0">{_esc(fallback)}</pre>\n'
            "</div>\n"
        )

    parts.append(
        '<div class="surface-card p-4 mb-4">\n'
        "  <details>\n"
        '    <summary class="small">レポートJSON全体</summary>\n'
        f'    <pre class="raw">{_esc(json.dumps(report, ensure_ascii=False, indent=2))}</pre>\n'
        "  </details>\n"
        "</div>\n"
    )

    return _page(f"JUSLAG 日次レポート {date}", "".join(parts), "../index.html")


def render_site(history: list[dict], reports: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reports").mkdir(exist_ok=True)
    (out_dir / "index.html").write_text(_render_index(history, reports), encoding="utf-8")
    for report in reports:
        date = report.get("date")
        if not date:
            continue
        (out_dir / "reports" / f"{date}.html").write_text(_render_report_page(report), encoding="utf-8")
