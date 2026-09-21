#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
audit_root=$(mktemp -d -t juslag-turso-audit-XXXXXXXX)
trap 'rm -rf -- "$audit_root"' EXIT

: "${JUSLAG_TURSO_DATABASE_URL:?JUSLAG_TURSO_DATABASE_URL is required}"
: "${JUSLAG_TURSO_AUTH_TOKEN:?JUSLAG_TURSO_AUTH_TOKEN is required}"

# Audit the committed source of truth, not a potentially stale or dirty checkout.
git -C "$repo_root" fetch --quiet origin main
git -C "$repo_root" archive --format=tar origin/main data/reports data/history.jsonl \
  | tar -xf - -C "$audit_root"

export PYTHONPATH="$repo_root/src"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/juslag-uv-cache}"
"$repo_root/.venv/bin/python" "$repo_root/scripts/ops/turso_reconcile.py" \
  --since 2026-07-09 \
  --reports "$audit_root/data/reports" \
  --history "$audit_root/data/history.jsonl"
