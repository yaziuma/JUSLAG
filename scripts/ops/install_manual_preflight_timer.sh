#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

install -d -m 0755 "$unit_dir"
install -m 0644 "$repo_root/config/systemd/juslag-manual-preflight.service" "$unit_dir/"
install -m 0644 "$repo_root/config/systemd/juslag-manual-preflight.timer" "$unit_dir/"
install -m 0644 "$repo_root/config/systemd/juslag-local-daily-report.service" "$unit_dir/"
install -m 0644 "$repo_root/config/systemd/juslag-local-daily-report.timer" "$unit_dir/"
systemctl --user daemon-reload
systemctl --user enable --now juslag-local-daily-report.timer juslag-manual-preflight.timer
systemctl --user list-timers juslag-local-daily-report.timer juslag-manual-preflight.timer --no-pager
