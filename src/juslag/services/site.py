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
  --bg-page: #0b1220;
  --bg-surface: #141c2e;
  --text-heading: #f1f5f9;
  --text-default: #cbd5e1;
  --text-muted: #8a97ac;
  --border-default: #2a3550;
  --accent: #3b82f6;
}
body {
  background: var(--bg-page);
  color: var(--text-default);
  font-family: -apple-system, "Segoe UI", "Hiragino Sans", "Noto Sans JP", sans-serif;
}
.navbar { background: var(--bg-surface); border-bottom: 1px solid var(--border-default) !important; }
.surface-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, .4);
}
.text-heading { color: var(--text-heading); }
.text-muted-soft { color: var(--text-muted); }
a { color: var(--accent); }
.table { color: var(--text-default); }
.table > :not(caption) > * > * { border-color: var(--border-default); }
pre.summary {
  white-space: pre-wrap; background: rgba(255,255,255,.03); border: 1px solid var(--border-default);
  border-radius: 6px; padding: 14px; font-size: .9rem; line-height: 1.6; color: var(--text-default);
}
pre.raw {
  background: rgba(255,255,255,.03); border: 1px solid var(--border-default); overflow-x: auto;
  padding: 12px; font-size: .75rem; color: var(--text-default);
}
details > summary { cursor: pointer; margin: 8px 0; color: var(--text-muted); }
.regime-strip { display: flex; flex-wrap: wrap; gap: 3px; }
.regime-cell { width: 14px; height: 28px; border-radius: 3px; flex-shrink: 0; }
.btn-group .btn.active { color: #fff; }
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
        '  <div class="container py-2 d-flex justify-content-between align-items-center">\n'
        f'    <a class="navbar-brand mb-0 h1 fw-semibold text-heading text-decoration-none" href="{_esc(home_href)}">'
        "JUSLAG 日次リサーチ</a>\n"
        "  </div>\n"
        "</nav>\n"
        f'<main class="container py-4">\n{body}\n</main>\n'
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
        cls = ds.get("no_trade_classification")
        rows.append(
            {
                "date": date,
                "href": f"reports/{date}.html",
                "tradeable": tradeable,
                "classification_label": _cls_label(cls) if not tradeable else "",
                "classification_variant": _cls_variant(cls),
                "trend_regime": ds.get("trend_regime"),
                "vol_regime": ds.get("vol_regime"),
                "rotation_regime": _rotation_regime(ds),
                "long": _plan_summary(plan.get("long")),
                "short": _plan_summary(plan.get("short")),
                "judge_score": judge.get("overall_score"),
                "judge_decision": judge.get("overall_decision"),
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


def _render_index(history: list[dict], reports: list[dict]) -> str:
    parts: list[str] = []

    # 最新サマリー
    if history:
        latest = history[-1]
        status = _esc(latest.get("llm_status"))
        parts.append(
            '<div class="surface-card p-4 mb-4">\n'
            '  <div class="d-flex justify-content-between align-items-center mb-2 flex-wrap gap-2">\n'
            '    <h2 class="h5 text-heading mb-0">最新サマリー</h2>\n'
            '    <span class="text-muted-soft small">'
            f'{_esc(latest.get("jst_date"))} '
            f'<span class="badge text-bg-secondary ms-1">LLM: {status}</span></span>\n'
            "  </div>\n"
            f'  <pre class="summary mb-0">{_esc(latest.get("summary"))}</pre>\n'
            "</div>\n"
        )
    else:
        parts.append('<div class="surface-card p-4 mb-4"><p class="mb-0">まだサマリー履歴がありません。</p></div>\n')

    # 日次履歴テーブル（Alpine）
    rows = _index_rows(reports)
    data_json = _json_embed({"rows": rows})
    parts.append(f"<script>window.__DATA__ = {data_json};</script>\n")
    parts.append(
        """
<script>
function historyTable() {
  return {
    filter: 'all',
    rows: (window.__DATA__ && window.__DATA__.rows) || [],
    get filteredRows() {
      if (this.filter === 'executed') return this.rows.filter(function (r) { return r.tradeable; });
      if (this.filter === 'skipped') return this.rows.filter(function (r) { return !r.tradeable; });
      return this.rows;
    }
  };
}
</script>
"""
    )
    parts.append(
        '<div class="surface-card p-4 mb-4" x-data="historyTable()">\n'
        '  <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">\n'
        '    <h2 class="h5 text-heading mb-0">日次履歴</h2>\n'
        '    <div class="btn-group btn-group-sm" role="group" aria-label="フィルタ">\n'
        '      <button type="button" class="btn btn-outline-secondary" '
        "@click=\"filter = 'all'\" :class=\"{active: filter === 'all'}\">全て</button>\n"
        '      <button type="button" class="btn btn-outline-secondary" '
        "@click=\"filter = 'executed'\" :class=\"{active: filter === 'executed'}\">執行のみ</button>\n"
        '      <button type="button" class="btn btn-outline-secondary" '
        "@click=\"filter = 'skipped'\" :class=\"{active: filter === 'skipped'}\">見送りのみ</button>\n"
        "    </div>\n"
        "  </div>\n"
        '  <div class="table-responsive">\n'
        '    <table class="table table-sm table-hover align-middle mb-0">\n'
        "      <thead><tr><th>日付</th><th>判定</th><th>レジーム</th><th>LONG</th>"
        "<th>SHORT</th><th>Judgeスコア</th><th>リンク</th></tr></thead>\n"
        "      <tbody>\n"
        '        <template x-for="row in filteredRows" :key="row.date">\n'
        "          <tr>\n"
        '            <td x-text="row.date"></td>\n'
        "            <td>\n"
        '              <span class="badge" :class="row.tradeable ? \'text-bg-success\' : \'text-bg-warning\'" '
        "x-text=\"row.tradeable ? '執行' : '見送り'\"></span>\n"
        '              <span class="badge ms-1" x-show="!row.tradeable" '
        ":class=\"'text-bg-' + row.classification_variant\" x-text=\"row.classification_label\"></span>\n"
        "            </td>\n"
        "            <td>\n"
        '              <span class="badge text-bg-light me-1" x-text="row.trend_regime || \'-\'"></span>\n'
        '              <span class="badge text-bg-light me-1" x-text="row.vol_regime || \'-\'"></span>\n'
        '              <span class="badge text-bg-light" x-text="row.rotation_regime || \'-\'"></span>\n'
        "            </td>\n"
        "            <td x-text=\"row.long || '-'\"></td>\n"
        "            <td x-text=\"row.short || '-'\"></td>\n"
        "            <td x-text=\"row.judge_score != null ? (row.judge_score + '（' + "
        "(row.judge_decision || '-') + '）') : '-'\"></td>\n"
        '            <td><a :href="row.href">詳細</a></td>\n'
        "          </tr>\n"
        "        </template>\n"
        "      </tbody>\n"
        "    </table>\n"
        "  </div>\n"
        '  <p class="small text-muted-soft mt-2 mb-0" x-show="filteredRows.length === 0">'
        "該当する日次データがありません。</p>\n"
        "</div>\n"
    )

    # レジーム推移
    parts.append(
        '<div class="surface-card p-4 mb-4">\n'
        '  <h2 class="h5 text-heading mb-2">レジーム推移</h2>\n'
        '  <p class="small text-muted-soft">セルにカーソルを合わせると日付とtrend/vol/rotationを表示します'
        "（緑=uptrend / 赤=downtrend / グレー=range・不明）。</p>\n"
        f"  {_regime_strip(reports)}\n"
        "</div>\n"
    )

    # 過去サマリー
    if len(history) > 1:
        parts.append('<div class="surface-card p-4 mb-4">\n  <h2 class="h5 text-heading mb-3">過去サマリー</h2>\n')
        for entry in reversed(history[:-1]):
            parts.append(
                "  <details>\n"
                f'    <summary>{_esc(entry.get("jst_date"))}'
                f'（LLM: {_esc(entry.get("llm_status"))}）</summary>\n'
                f'    <pre class="summary">{_esc(entry.get("summary"))}</pre>\n'
                "  </details>\n"
            )
        parts.append("</div>\n")

    return _page("JUSLAG 日次リサーチ", "".join(parts), "index.html")


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
