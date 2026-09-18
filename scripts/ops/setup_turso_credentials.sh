#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: %s <database-name> [--replace]\n' "$0" >&2
  exit 2
}

[[ $# -ge 1 && $# -le 2 ]] || usage
db_name=$1
[[ $# -eq 1 || $2 == --replace ]] || usage
command -v turso >/dev/null || { printf 'turso CLI is required\n' >&2; exit 1; }

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
output="$repo_root/.env.turso"
if [[ -e $output && ${2:-} != --replace ]]; then
  printf '%s already exists; use --replace to rotate it\n' "$output" >&2
  exit 1
fi

database_url=$(turso db show "$db_name" --url)
if [[ ! $database_url =~ ^(libsql|https|turso)://[^[:space:]]+$ ]]; then
  printf 'Could not read a valid database URL; check turso auth login --headless\n' >&2
  exit 1
fi
auth_token=$(turso db tokens create "$db_name" --expiration 30d)
if [[ ! $auth_token =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$ ]]; then
  printf 'Could not create a valid database token; check Turso CLI authentication\n' >&2
  exit 1
fi

umask 077
temp_file=$(mktemp "$repo_root/.env.turso.XXXXXX")
trap 'rm -f "$temp_file"' EXIT
printf 'JUSLAG_TURSO_DATABASE_URL=%q\nJUSLAG_TURSO_AUTH_TOKEN=%q\n' \
  "$database_url" "$auth_token" > "$temp_file"
mv -f "$temp_file" "$output"
trap - EXIT
printf 'Stored Turso credentials in %s (mode 600; token expires in 30 days)\n' "$output"
