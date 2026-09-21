#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

if [[ ! -s "$repo_root/.env.turso" ]]; then
  echo "Missing $repo_root/.env.turso; see docs/turso_credentials.md" >&2
  exit 1
fi

install -d -m 0755 "$unit_dir"
install -m 0644 "$repo_root/config/systemd/juslag-turso-reconcile.service" "$unit_dir/"
install -m 0644 "$repo_root/config/systemd/juslag-turso-reconcile.timer" "$unit_dir/"
systemctl --user daemon-reload
systemctl --user enable --now juslag-turso-reconcile.timer
systemctl --user list-timers juslag-turso-reconcile.timer --no-pager

