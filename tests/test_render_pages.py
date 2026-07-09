from __future__ import annotations

import json
from pathlib import Path

from juslag.services.site import load_history, load_reports, render_site


def _write_report(reports_dir: Path, date: str, tradeable: bool) -> None:
    report = {
        "schema_version": 1,
        "date": date,
        "generated_at_utc": f"{date}T00:00:00+00:00",
        "backtest": {
            "settings_name": "本番適用 test",
            "judge": {
                "overall_score": 80,
                "overall_decision": "pass",
                "summary": "総合的に良好です。",
                "category_scores": {
                    "profitability": 25,
                    "stability": 20,
                    "cost_resilience": 15,
                    "executability": 10,
                    "data_reliability": 10,
                },
                "category_decisions": {
                    "profitability": "pass",
                    "stability": "pass",
                    "cost_resilience": "warn",
                    "executability": "pass",
                    "data_reliability": "pass",
                },
                "reasons": [
                    {"code": "SOME_CODE", "severity": "warn", "message": "参考情報です。"},
                ],
                "actions": ["継続モニタリングしてください。"],
            },
        },
        "daily_signal": {
            "execution_target_jp_date": date,
            "signal_reference_us_date": date,
            "tradeable": tradeable,
            "trade_block_reason": None if tradeable else "strategy_rule_skip",
            "no_trade_classification": None if tradeable else "strategy_rule_skip",
            "trend_regime": "uptrend",
            "vol_regime": "normal",
            "strategy_context": {"rotation_regime": "rotating"},
            "execution_plan": {
                "long": [{"ticker": "1625.T", "sector": "電機・精密", "weight": 20.0}],
                "short": [{"ticker": "1630.T", "sector": "小売", "weight": 25.0}],
            },
            "strategy_decision": {
                "rule_id": "rule_406",
                "rule_name_ja": "テストルール",
                "action": "execute" if tradeable else "skip",
                "reason_ja": "テスト判定理由テキスト",
            },
            "candidate_signal_stats": {
                "long_threshold": 0.0,
                "short_threshold": 0.0,
                "top_long_candidates": [
                    {"ticker": "1625.T", "sector": "電機・精密", "signal": 0.12, "gap_to_threshold": 0.12, "passes": True}
                ],
                "top_short_candidates": [
                    {"ticker": "1630.T", "sector": "小売", "signal": -0.08, "gap_to_threshold": 0.08, "passes": True}
                ],
            },
            "rows": [
                {"ticker": "1625.T", "sector": "電機・精密", "signal": 0.12, "position": "LONG"},
                {"ticker": "1630.T", "sector": "小売", "signal": -0.08, "position": "SHORT"},
            ],
        },
        "slack_fallback_text": f"summary for {date}",
    }
    (reports_dir / f"{date}.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )


def test_render_site_produces_index_and_report_pages(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True)

    _write_report(reports_dir, "2026-07-07", tradeable=False)
    _write_report(reports_dir, "2026-07-08", tradeable=True)

    history_lines = [
        {
            "date": "2026-07-07T00:00:00Z",
            "jst_date": "2026-07-07",
            "summary": "初日サマリー",
            "llm_status": "ok",
            "report": "data/reports/2026-07-07.json",
        },
        {
            "date": "2026-07-08T00:00:00Z",
            "jst_date": "2026-07-08",
            "summary": "最新サマリー本文",
            "llm_status": "ok",
            "report": "data/reports/2026-07-08.json",
        },
    ]
    history_path = data_dir / "history.jsonl"
    history_path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in history_lines) + "\n",
        encoding="utf-8",
    )

    history = load_history(history_path)
    reports = load_reports(reports_dir)
    assert len(history) == 2
    assert len(reports) == 2

    out_dir = tmp_path / "site"
    render_site(history, reports, out_dir)

    index_path = out_dir / "index.html"
    assert index_path.exists()
    index_html = index_path.read_text(encoding="utf-8")

    # 最新サマリー
    assert "最新サマリー本文" in index_html

    # 両方のレポートページへのリンク（Alpine embedded data経由）
    assert "reports/2026-07-07.html" in index_html
    assert "reports/2026-07-08.html" in index_html

    # 埋め込みデータ script タグ
    assert "window.__DATA__" in index_html

    # フィルタUI（Alpine制御の全て/執行のみ/見送りのみ）
    assert "執行のみ" in index_html
    assert "見送りのみ" in index_html

    # CDNアセット（B-FADスタック: Bootstrap 5 + Alpine.js, ビルド不要）
    assert "cdn.jsdelivr.net/npm/bootstrap@" in index_html
    assert "cdn.jsdelivr.net/npm/alpinejs@" in index_html

    assert (out_dir / "reports" / "2026-07-07.html").exists()
    assert (out_dir / "reports" / "2026-07-08.html").exists()

    report_html = (out_dir / "reports" / "2026-07-08.html").read_text(encoding="utf-8")
    assert "summary for 2026-07-08" in report_html

    # Judgeスコアと戦略ルールの判定理由
    assert "80" in report_html
    assert "テスト判定理由テキスト" in report_html

    # サイト全体にJSONファイルは出力しない（HTML単位でパスワード保護するため）
    assert not any(out_dir.rglob("*.json"))
