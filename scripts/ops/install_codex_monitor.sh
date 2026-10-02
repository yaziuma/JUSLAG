#!/usr/bin/env bash
set -euo pipefail

thread_id=${1:?usage: install_codex_monitor.sh THREAD_ID}
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
unit_dir=${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user
config_dir=${XDG_CONFIG_HOME:-${HOME}/.config}/juslag

install -d -m 0700 "${config_dir}"
install -d -m 0755 "${unit_dir}"
printf 'JUSLAG_CODEX_THREAD_ID=%s\n' "${thread_id}" >"${config_dir}/codex-monitor.env"
chmod 0600 "${config_dir}/codex-monitor.env"
install -m 0644 "${repo_root}/config/systemd/juslag-codex-monitor@.service" "${unit_dir}/"
install -m 0644 "${repo_root}/config/systemd/juslag-codex-monitor.timer" "${unit_dir}/"

systemctl --user daemon-reload
systemctl --user enable --now juslag-codex-monitor.timer
