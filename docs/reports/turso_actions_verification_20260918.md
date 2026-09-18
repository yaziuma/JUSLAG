# Turso日次同期・GitHub Actions実証（2026-09-18）

## 既存全期間の投入（2026-09-18）

Git正本の`2026-07-09`〜`2026-09-17`の未投入51日を既存Cloud DBへ一括再送した。別接続による読み戻しは`PASS: reconciled 51 date(s)`。改めて全期間を読み取り専用監査すると`Audit: 0 date(s) require repair since 2026-07-09`。公式CLIから直接SQLで`54`行、`52`日、最初`2026-07-09`、最新`2026-09-18`を確認した。追加の2行は9月18日の同日再実行分で、最新run選択の対象は52日分。

`turso db inspect`の直後表示は書込行数が投入前と変わらず、容量が`0 B`になるなど集計遅延または表示不整合が見られたため、これを投入失敗とは判定しない。データ存在と内容一致は直接SQL・別接続・Git照合で確認した。使用量は後日改めて測定する。以後の定期照合の既定開始日を最初のレポート日へ変更し、全期間の差分を追う。

## 到達点

- `pyturso==0.7.2`を`turso` extraで固定。`scripts/ops/turso_daily.py`が確定済みのレポートJSONと同日`history.jsonl`の最後の要約を1行の`juslag_daily_snapshots`としてCloud Syncへpushする。別の一時ローカルDBからpullし、内容SHA-256を照合する。読取CLIも同じハッシュを検証し、600権限のファイルへ出力する。
- `run_id`が同じで内容が同じなら再送はno-op、内容が異なればエラー。同日再実行は別runで保持。書込は`JUSLAG_WRITE_TURSO=1`、Actionsではリポジトリ変数`true`の時だけ。DBトークンはActions Secret、URLはVariable、ブラウザにはどちらも渡さない。既知トークンとSlack Webhookが本文に混入すれば公開を拒否する。
- ローカルで実データ`2026-09-18.json`をCloudへ保存・読取し、元JSONとSHA-256一致。手動[Actionsスモーク #35310686146](https://github.com/yaziuma/JUSLAG/actions/runs/35310686146)は書込・読取・`cmp`が成功。
- `JUSLAG_WRITE_TURSO=true`を設定した[日次Actions #35310809472](https://github.com/yaziuma/JUSLAG/actions/runs/35310809472)では、研究・Git保存・Turso・Pagesの全ジョブが成功。Tursoの`run_id=actions:35310809472:1`を独立CLIで読み戻し、Gitに保存された同日レポートとSHA-256一致。`main`は日次データcommit`fef2cdb`まで取得済み。
- `.venv/bin/pytest -q`: 241 passed、40 warnings（既存Pandas4Warning）。Ruff、bash構文、workflow YAML、`uv lock --check`、`git diff --check`も通過。

## 運用と残件

- 旧ファイル、Slack、Pagesを維持する。Tursoジョブは研究完了後の別ジョブなので、Turso障害はそれらを巻き戻さない。停止は`gh variable set JUSLAG_WRITE_TURSO --body false --repo yaziuma/JUSLAG`。30日期限のトークンは期限前に更新し、Actions Secretも更新する。
- Sync方式はActions一時DBで毎回Cloudをpullする。PoC前の`db inspect`は12 kB/読取41/書込21/Sync 90 kB、Actionsとローカル読取後は98 kB/読取135/書込41/Sync 778 kB。間に複数の試行・照合があり、差分を単一実行の請求量とはみなさない。月間3 GB枠・Overages無効。履歴増大時のbootstrap量を監視する。
- 全B0/B1ゲートは未達。内部テーブル警告の原因、Cloud再インポート、10回連続照合、使用量アラート、認証付きViewerは別途必要。これは研究結果の保存であり、発注許可ではない。

## 2026-09-18 照合・再送の追加

- `turso-reconcile.yml`はGit上の運用開始日以降の確定レポートとCloudの最新runを毎平日比較する。欠落・差分を最大10日分修復し、別接続から内容ハッシュを読み戻す。上限超過なら書き込まず失敗、次回再試行する。手動実行は既定で監査のみ。
- Cloudへのアクセスは一時DBの最初のpull、修復時のpush、別接続の検証pull。対象日数に比例するCloud pullは行わない。Cloud障害・トークン失効時は失敗通知のみでGit正本を維持する。実運用10回連続照合と失敗復旧は今後確認する。

## 2026-09-18 ローカルSync復旧訓練

- 公式の`tursodb 0.7.2 --sync-server`と`pyturso 0.7.2`で、使い捨てDBに対し`scripts/ops/turso_recovery_drill.py`を実行した。欠落の補填、Git側の要約変更による差分修復、サーバー停止中のpush失敗、復帰後の同一`run_id`再送、別クライアントからの読み戻し、重複行なしを確認し、全検査がPASS。
- 訓練中、ローカルcommit後にpushだけ失敗した場合、従来の「行挿入時のみpush」では未送信分を再送できないことを発見。修復処理は同一`run_id`が既にローカルにあってもpushを再実行するよう修正し、ユニットテストにも追加した。
- 本番Cloudの行は変更していない。Cloud障害からの実復旧、10回連続の日次照合、Cloud再インポート、Sync使用量アラートは未検証。公式の[ローカルSyncサーバー手順](https://docs.turso.tech/sync/local-sync-server)に沿う訓練であり、Cloud障害を完全に代替するものではない。
