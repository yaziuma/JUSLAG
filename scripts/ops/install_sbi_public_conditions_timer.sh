#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

install -d -m 0755 "$unit_dir"
install -m 0644 "$repo_root/config/systemd/juslag-sbi-public-conditions.service" "$unit_dir/"
install -m 0644 "$repo_root/config/systemd/juslag-sbi-public-conditions.timer" "$unit_dir/"
systemctl --user daemon-reload
systemctl --user enable --now juslag-sbi-public-conditions.timer
systemctl --user list-timers juslag-sbi-public-conditions.timer --no-pager

