from __future__ import annotations

import json
import urllib.request
from datetime import datetime


def _fmt_pct_raw(v: float | None, signed: bool = True) -> str:
    if v is None:
        return "-"
    return f"{v:+.2f}%" if signed else f"{v:.2f}%"


def build_slack_summary(bt: dict, ds: dict, now_jst: datetime) -> str:
    now = now_jst.strftime("%Y-%m-%d %H:%M JST")
    judge = bt.get("judge") or {}
    score = judge.get("overall_score", "-")
    decision = judge.get("overall_decision", "-")
    na_list = (bt.get("performance_sets") or {}).get("net_after_tax", [{}])
    na = na_list[0] if na_list else {}
    ar_str = _fmt_pct_raw(na.get("AR(%)"))
    rr = na.get("R/R")
    rr_str = f"{rr:.3f}" if rr is not None else "-"
    mdd_str = _fmt_pct_raw(na.get("MDD(%)"), signed=False)

    exec_date = ds.get("execution_target_jp_date", "-")
    us_ref_date = str(ds.get("signal_reference_us_date") or "-")[:10]
    today_str = now_jst.date().isoformat()
    exec_date_note = " ⚠️ 過去日" if exec_date < today_str else ""
    tradeable = ds.get("tradeable", False)
    trade_icon = "✅" if tradeable else "⏸"
    block_reason = ds.get("trade_block_reason") or ""
    trade_str = f"{trade_icon} 売買あり" if tradeable else f"{trade_icon} 見送り"
    if block_reason:
        trade_str += f" — {block_reason}"

    ep = ds.get("execution_plan") or {}
    long_sectors = ", ".join(e["sector"] for e in ep.get("long", [])) or "なし"
    short_sectors = ", ".join(e["sector"] for e in ep.get("short", [])) or "なし"

    trend = ds.get("trend_regime", "-")
    vol = ds.get("vol_regime", "-")
    sc = ds.get("strategy_context") or {}
    rotation = sc.get("rotation_regime") or ds.get("rotation_regime", "-")
    regime_line = f"Regime: {trend} / {vol} / rotation={rotation}"
    if ds.get("regime_warning"):
        reason = ds.get("regime_warning_reason") or ""
        regime_line += f"  ⚠️ {reason}"

    no_trade_cls = ds.get("no_trade_classification")
    cls_labels = {
        "strategy_rule_skip_with_candidates": "戦略ルール見送り（候補あり）",
        "strategy_rule_skip": "戦略ルール見送り",
        "near_miss_threshold": "惜しい（閾値に近い）",
        "one_side_only": "片側不足",
        "regime_blocked": "Regime警告（強度あり）",
        "hard_no_signal": "シグナルなし（遠い）",
    }
    cls_str = cls_labels.get(no_trade_cls, no_trade_cls) if no_trade_cls else ""

    stats = ds.get("candidate_signal_stats") or {}
    cand_str = f"{ds.get('candidate_signal_strength', 0.0):.4f}"
    adpt_str = f"{ds.get('adopted_signal_strength', 0.0):.4f}"
    long_th = stats.get("long_threshold", 0.10)
    short_th = stats.get("short_threshold", -0.10)
    top_long = stats.get("top_long_candidates") or []
    top_short = stats.get("top_short_candidates") or []
    all_rows = sorted(ds.get("rows") or [], key=lambda r: r.get("signal", 0), reverse=True)

    def _fmt_candidate_rows(candidates: list) -> list[str]:
        result = []
        for i, c in enumerate(candidates, 1):
            ticker = c.get("ticker", "")
            sector = c.get("sector", "")
            sig = c.get("signal", 0.0)
            gap = c.get("gap_to_threshold", 0.0)
            mark = "✅" if c.get("passes") else "  "
            result.append(f"{mark} {i}. {ticker}  {sector}  {sig:+.4f}  差:{gap:+.4f}")
        return result

    long_rows_lines = _fmt_candidate_rows(top_long)
    short_rows_lines = _fmt_candidate_rows(top_short)

    sig_max = stats.get("signal_max")
    sig_min = stats.get("signal_min")
    sig_p50 = stats.get("signal_p50")
    all_stats_line = (
        f"全{len(all_rows)}銘柄: 最大 {sig_max:+.4f} / 中央値 {sig_p50:+.4f} / 最小 {sig_min:+.4f}"
        if sig_max is not None else ""
    )
    long_gap_max = stats.get("long_threshold_gap_max")
    short_gap_max = stats.get("short_threshold_gap_max")
    long_gap_line = f"最大LONG {stats.get('top_long_candidates',[{}])[0].get('signal',0):+.4f} — 閾値まで {long_gap_max:+.4f}" if top_long and long_gap_max is not None else ""
    short_gap_line = f"最小SHORT {stats.get('top_short_candidates',[{}])[0].get('signal',0):+.4f} — 閾値まで {short_gap_max:+.4f}" if top_short and short_gap_max is not None else ""

    lines = [
        f"*JUSLAG 朝次実行完了* ({now})",
        "",
        "*バックテスト（本番適用設定）*",
        f"  Judge: {score}点 / {decision}  |  Net After AR: {ar_str}  |  R/R: {rr_str}  |  MDD: {mdd_str}",
        "",
        f"*本日シグナル* (執行日: {exec_date}{exec_date_note}  |  US参照: {us_ref_date})",
        f"  {trade_str}",
        f"  LONG:  {long_sectors}",
        f"  SHORT: {short_sectors}",
        f"  {regime_line}",
    ]
    if cls_str:
        lines.append(f"  見送り理由: {cls_str}")

    if block_reason == "strategy_rule_skip":
        sd = ds.get("strategy_decision") or {}
        pre_l = ds.get("pre_rule_adopted_long_count") or 0
        pre_s = ds.get("pre_rule_adopted_short_count") or 0
        post_l = ds.get("post_rule_adopted_long_count") or 0
        post_s = ds.get("post_rule_adopted_short_count") or 0
        open_gap_val = sc.get("open_gap")
        open_gap_str = f"{open_gap_val*100:+.2f}%" if open_gap_val is not None else "欠損"
        lines += [
            f"  ルール: {sd.get('rule_name_ja', '-')}  フィルタ: {sd.get('matched_filter', '-')}",
            f"  理由: {sd.get('reason_ja', '-')}",
            f"  元シグナル: LONG {pre_l}件 / SHORT {pre_s}件  →  最終実行: LONG {post_l}件 / SHORT {post_s}件",
            f"  open_gap: {open_gap_str}  rotation: {rotation}",
        ]

    lines += [
        "",
        f"*シグナル詳細*  候補強度: {cand_str}  採用強度: {adpt_str}",
        "```",
        f"LONG候補上位（閾値: ≥{long_th}）",
    ]
    lines += long_rows_lines
    if long_gap_line:
        lines.append(long_gap_line)
    lines += ["", f"SHORT候補下位（閾値: ≤{short_th}）"]
    lines += short_rows_lines
    if short_gap_line:
        lines.append(short_gap_line)
    if all_stats_line:
        lines += ["", all_stats_line]
    lines.append("```")

    return "\n".join(lines)


def build_failure_message(traceback_text: str, now_jst: datetime) -> str:
    now = now_jst.strftime("%Y-%m-%d %H:%M JST")
    return f"*JUSLAG 朝次実行エラー* ({now})\n```{traceback_text[-1500:]}```"


def send_slack(webhook_url: str, text: str, timeout: int = 10) -> bool:
    if not webhook_url:
        return False
    data = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False
