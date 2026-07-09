#!/usr/bin/env python3
"""JUSLAG 日次リサーチバッチ本体（HTTP/FastAPI非依存・ライブラリ直呼び出し）。

手順:
  1. 一括データ取込（raw + adjusted + factors + actions） ※ --skip-fetch で省略可
  2. データステータス評価
  3. 「本番適用」設定でバックテスト
  4. 本日のシグナル計算
  5. 戦略履歴の保存（strategy_history.jsonl）
  6. Slackフォールバック文面の生成
  7. 日次レポートJSONの書き出し
  8. 監査用の生データ・処理済みデータの抽出

実行例:
    uv run python scripts/ops/daily_research.py --date 2026-07-08
    uv run python scripts/ops/daily_research.py --skip-fetch --out-dir /tmp/juslag_data
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from juslag.cache import PriceCache
from juslag.config import AppConfig, JP_TICKERS, US_TICKERS
from juslag.services.backtest import run_backtest_service
from juslag.services.daily_report import _to_jsonable, build_daily_report
from juslag.services.daily_signal import run_daily_signal_service
from juslag.services.data_status import build_data_status
from juslag.services.fetch_all import run_fetch_all
from juslag.services.notify import build_slack_summary
from juslag.services.settings import load_production_backtest_params
from juslag.services.store import build_strategy_history_entry

_JST = ZoneInfo("Asia/Tokyo")
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="対象日 (JST, YYYY-MM-DD)。省略時は現在のAsia/Tokyo日付。",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="データ取込（手順1）を省略する（ローカル動作確認用）。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    now_actual = datetime.now(_JST)
    target_date: date_cls = (
        datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else now_actual.date()
    )
    date_str = target_date.isoformat()
    now_jst = datetime.combine(target_date, now_actual.time(), tzinfo=_JST)

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = AppConfig.load(_REPO_ROOT / "config" / "app.yaml")
    cache = PriceCache()

    # --- 1. データ取込 ---
    if args.skip_fetch:
        fetch_result: dict = {"status": "skipped", "steps": {}, "error_summary": []}
    else:
        fetch_end = (target_date + timedelta(days=1)).isoformat()
        fetch_result = run_fetch_all(
            "2010-01-01",
            fetch_end,
            ["raw", "adjusted"],
            include_factors=True,
            include_actions=True,
            project_root=_REPO_ROOT,
            cache=cache,
        )
        steps = fetch_result.get("steps") or {}
        price_errors = [
            name
            for name, step in steps.items()
            if name.startswith("price_") and step.get("status") == "error"
        ]
        if price_errors:
            for name in price_errors:
                print(f"[error] fetch step failed: {name}: {steps[name].get('error')}", file=sys.stderr)
            sys.exit(1)

    # --- 2. データステータス評価 ---
    analysis_status = build_data_status(
        cache,
        cfg,
        external_dir=_REPO_ROOT / "data" / "external",
        report_path=_REPO_ROOT / "outputs" / "juslag_report.json",
    )

    # --- 3. バックテスト（本番適用設定） ---
    params, settings_name = load_production_backtest_params()
    bt = run_backtest_service(params, cache, analysis_status=analysis_status)

    # --- 4. 本日のシグナル ---
    ds = run_daily_signal_service(
        cfg,
        cache,
        log_path=_REPO_ROOT / cfg.output_dir / "daily_signal_log.csv",
        analysis_status=analysis_status,
        now_jst=now_jst,
        active_rule_id=params.strategy_rule_id or None,
    )

    # --- 5. 戦略履歴の保存 ---
    entry = build_strategy_history_entry(ds, now_jst)
    history_entry_dict = _to_jsonable(entry.model_dump(exclude={"raw_signal_json"}))
    history_jsonl_path = out_dir / "strategy_history.jsonl"
    with history_jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(history_entry_dict, ensure_ascii=False) + "\n")

    # --- 6. Slackフォールバック文面 ---
    slack_text = build_slack_summary(bt, ds, now_jst)

    # --- 7. 日次レポートJSON ---
    generated_at_utc = datetime.now(timezone.utc).isoformat()
    report = build_daily_report(
        date=date_str,
        bt=bt,
        ds=ds,
        fetch_result=fetch_result,
        params=params,
        settings_name=settings_name,
        history_entry=history_entry_dict,
        slack_fallback_text=slack_text,
        generated_at_utc=generated_at_utc,
    )
    report_path = out_dir / "reports" / f"{date_str}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- 8. 監査用データ抽出 ---
    all_tickers = list(US_TICKERS.keys()) + list(JP_TICKERS.keys())
    since_date = (target_date - timedelta(days=7)).isoformat()
    raw_dir = out_dir / "raw" / date_str
    for mode, filename in (("raw", "prices_tail_raw.csv"), ("adjusted", "prices_tail_adjusted.csv")):
        tail_df = cache.export_tail(all_tickers, since_date, mode)
        if args.skip_fetch and tail_df.empty:
            continue
        raw_dir.mkdir(parents=True, exist_ok=True)
        tail_df.to_csv(raw_dir / filename, index=False)

    for meta_name in ("ff3_metadata.json", "actions_metadata.json"):
        subdir = "factors" if meta_name.startswith("ff3") else "actions"
        src = _REPO_ROOT / "data" / "external" / subdir / "normalized" / meta_name
        if src.exists():
            raw_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, raw_dir / meta_name)

    processed_dir = out_dir / "processed" / date_str
    processed_dir.mkdir(parents=True, exist_ok=True)
    signals_df = pd.DataFrame(ds.get("rows") or [])
    signals_df.to_csv(processed_dir / "signals.csv", index=False)
    rotation = (ds.get("strategy_context") or {}).get("rotation_regime") or ds.get("rotation_regime")
    regime = {
        "trend_regime": ds.get("trend_regime"),
        "vol_regime": ds.get("vol_regime"),
        "rotation_regime": rotation,
    }
    (processed_dir / "regime.json").write_text(
        json.dumps(_to_jsonable(regime), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"REPORT_PATH={report_path}")


if __name__ == "__main__":
    main()
