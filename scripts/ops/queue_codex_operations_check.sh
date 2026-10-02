#!/usr/bin/env bash
set -euo pipefail

thread_id=${JUSLAG_CODEX_THREAD_ID:?JUSLAG_CODEX_THREAD_ID is required}
phase=${1:-periodic}

message="JUSLAG定期運用確認 (${phase})。ユーザーへ確認コマンドを要求せず、自分で実行状態と成果物を確認すること。承認API、Tailscale /healthz、signal/preflight/order sheet、intent publisher、承認待ち・期限切れ、execution ledger、SBI実発注経路を確認する。異常または未完成を見つけたら、原因を特定し、安全な範囲で修正・テスト・反映まで進める。実発注E2Eが未確認なら正常扱い・完了扱いにしない。確認結果と次の具体的作業をこのスレッドに記録すること。"

exec codex queue --thread "${thread_id}" --message "${message}"
