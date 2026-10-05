# Codexによる定期運用確認

JUSLAGの運用確認は、人がログを見に行く方式ではなく、systemdユーザータイマーが`codex queue`で運用中のCodexスレッドを起動する。Codexは各回で状態を確認し、異常または未完成があれば診断、修正、テスト、反映を継続する。

確認時刻（Asia/Tokyo）は次の通り。

- 日曜19:00: 翌週の事前確認
- 平日07:30、08:40、08:43: 寄付き前、最終signal、intent公開直後
- 平日08:50、08:56、09:10、09:42: 承認期限前、期限直後、寄付き後、開始値取得再試行後
- 平日15:35: 引け後の実績・失敗確認

タイマーはユーザー権限で動き、sudoを必要としない。対象スレッドIDは`~/.config/juslag/codex-monitor.env`へ0600で保存する。

```bash
bash scripts/ops/install_codex_monitor.sh '<thread-id>'
systemctl --user list-timers juslag-codex-monitor.timer
```

これは注文処理そのものではなく、運用状態をCodexが定期検証するための起動経路である。実発注E2Eが未確認の間は、サービスが稼働しているだけで完成または正常とは判定しない。
