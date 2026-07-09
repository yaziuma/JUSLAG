#!/usr/bin/env bash
# JUSLAG 日次リサーチバッチのオーケストレーション（GitHub Actions / ローカル共用）
#
# 環境変数:
#   JUSLAG_SLACK_WEBHOOK           Slack Incoming Webhook URL（未設定なら通知スキップ）
#   JUSLAG_BACKTEST_SETTINGS_JSON  本番バックテスト設定JSON（GitHub Variables から注入）
#   LLM_CMD        要約に使うCLI（デフォルト: agy）
#   LLM_MODEL      モデル指定（任意。指定時は --model を付与）
#   LLM_EXTRA_ARGS 追加引数（任意。例: "--print-timeout 3m"。スペース区切りで展開）
#   LLM_TIMEOUT    要約のタイムアウト秒（デフォルト: 180）
#   SKIP_LLM     1でLLM要約をスキップ（フォールバック文面を使用）
#   SKIP_SLACK   1でSlack通知をスキップ
#   JUSLAG_DATE  対象日（JST, YYYY-MM-DD。デフォルト: 当日）
set -euo pipefail

cd "$(dirname "$0")/../.."

JST_DATE="${JUSLAG_DATE:-$(TZ=Asia/Tokyo date +%F)}"
REPORT="data/reports/${JST_DATE}.json"
HISTORY="data/history.jsonl"
LLM_CMD="${LLM_CMD:-agy}"
LLM_TIMEOUT="${LLM_TIMEOUT:-180}"
LLM_STATUS="skipped"
SLACK_STATUS="skipped"

emit_output() {
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "$1=$2" >> "$GITHUB_OUTPUT"
  fi
}

notify_slack() {
  # $1: text。失敗しても呼び出し元を止めない（戻り値で伝える）
  if [ "${SKIP_SLACK:-0}" = "1" ] || [ -z "${JUSLAG_SLACK_WEBHOOK:-}" ]; then
    echo "[slack] skipped"
    return 0
  fi
  jq -n --arg text "$1" '{text: $text}' \
    | curl -fsS --max-time 15 -H 'Content-Type: application/json' -d @- "$JUSLAG_SLACK_WEBHOOK" > /dev/null
}

on_core_failure() {
  # JUSLAG本体の失敗: 保存も通知もせずワークフロー失敗（失敗通知のみ送る）
  notify_slack "*JUSLAG 日次リサーチ失敗* (${JST_DATE})
daily_research.py が異常終了しました。GitHub Actions のログを確認してください。" || true
  emit_output llm_status "not_run"
  emit_output slack_status "not_run"
  exit 1
}

# --- 1. 前回サマリーの読み込み ---
PREV_SUMMARY=""
if [ -f "$HISTORY" ]; then
  PREV_SUMMARY=$(tail -n 1 "$HISTORY" | jq -r '.summary // empty' 2>/dev/null || true)
fi

# --- 2. JUSLAG本体（失敗したら即終了・何も保存しない） ---
trap on_core_failure ERR
uv run python scripts/ops/daily_research.py --date "$JST_DATE"
trap - ERR

if [ ! -f "$REPORT" ]; then
  echo "[error] report not found: $REPORT" >&2
  on_core_failure
fi

# --- 3. LLM要約（失敗しても止めない: 生レポートへフォールバック） ---
FALLBACK_TEXT=$(jq -r '.slack_fallback_text // "（フォールバック文面なし）"' "$REPORT")
SUMMARY="$FALLBACK_TEXT"

if [ "${SKIP_LLM:-0}" != "1" ]; then
  PROMPT_FILE=$(mktemp "${RUNNER_TEMP:-/tmp}/juslag_prompt.XXXXXX")
  {
    cat <<'EOF'
あなたは日米業種リードラグ戦略（JUSLAG）の担当クオンツアナリストです。
以下の本日の分析結果JSONと前回サマリーをもとに、Slack投稿用の日本語サマリーを作成してください。

要件:
- 冒頭は「🤖 本日のJUSLAG定期リサーチ結果 (日付)」
- 含める内容: レジーム判定 / 主要シグナルとLONG・SHORT / 注目メタ戦略（Rule 406系）の判定 / 前回からの変化 / 判断上の注意点
- 前回からの変化（レジーム変化、シグナル点灯・消灯、LONG/SHORT入れ替わり）を最優先で強調する
- 見送り（skip）の場合はその分類と理由を明確に書く
- Slackでそのまま読める plain text（マークダウン見出しなし、箇条書きは「-」）で400字程度
- 事実はJSONに基づき、推測で数値を作らない

EOF
    echo "## 前回サマリー"
    if [ -n "$PREV_SUMMARY" ]; then echo "$PREV_SUMMARY"; else echo "（初回実行のため前回サマリーなし）"; fi
    echo
    echo "## 本日の分析結果JSON"
    jq '{date, backtest: {judge: .backtest.judge, performance_sets: .backtest.performance_sets}, daily_signal: (.daily_signal | del(.rows))}' "$REPORT"
  } > "$PROMPT_FILE"

  LLM_ARGS=(-p "$(cat "$PROMPT_FILE")")
  if [ -n "${LLM_MODEL:-}" ]; then
    LLM_ARGS=(--model "$LLM_MODEL" "${LLM_ARGS[@]}")
  fi
  if [ -n "${LLM_EXTRA_ARGS:-}" ]; then
    # shellcheck disable=SC2206
    LLM_ARGS=(${LLM_EXTRA_ARGS} "${LLM_ARGS[@]}")
  fi
  if ! command -v "$LLM_CMD" > /dev/null 2>&1; then
    echo "[llm] command not found: $LLM_CMD" >&2
    LLM_STATUS="failed"
  else
    LLM_ERR_FILE=$(mktemp "${RUNNER_TEMP:-/tmp}/juslag_llm_err.XXXXXX")
    if LLM_OUT=$(timeout "$LLM_TIMEOUT" "$LLM_CMD" "${LLM_ARGS[@]}" 2>"$LLM_ERR_FILE") \
        && [ -n "${LLM_OUT// /}" ]; then
      SUMMARY="$LLM_OUT"
      LLM_STATUS="ok"
    else
      echo "[llm] summarization failed (exit=$?); falling back to raw report text" >&2
      echo "[llm] stderr (last 30 lines):" >&2
      tail -n 30 "$LLM_ERR_FILE" >&2 || true
      LLM_STATUS="failed"
    fi
    rm -f "$LLM_ERR_FILE"
  fi
  rm -f "$PROMPT_FILE"
fi

# --- 4. history.jsonl へ追記 ---
jq -cn \
  --arg date "$(date -u +%FT%TZ)" \
  --arg jst_date "$JST_DATE" \
  --arg summary "$SUMMARY" \
  --arg llm_status "$LLM_STATUS" \
  --arg report "$REPORT" \
  '{date: $date, jst_date: $jst_date, summary: $summary, llm_status: $llm_status, report: $report}' \
  >> "$HISTORY"

# --- 5. Slack通知（失敗しても保存・コミットは活かす） ---
if notify_slack "$SUMMARY"; then
  if [ "${SKIP_SLACK:-0}" != "1" ] && [ -n "${JUSLAG_SLACK_WEBHOOK:-}" ]; then
    SLACK_STATUS="ok"
  fi
else
  echo "[slack] notification failed" >&2
  SLACK_STATUS="failed"
fi

emit_output llm_status "$LLM_STATUS"
emit_output slack_status "$SLACK_STATUS"
echo "[done] date=${JST_DATE} llm=${LLM_STATUS} slack=${SLACK_STATUS} report=${REPORT}"
