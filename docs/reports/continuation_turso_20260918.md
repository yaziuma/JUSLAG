# Turso作業引き継ぎ（2026-09-18）

## 現在地

- 作業場所は`/home/quieter/projects/JUSLAG`。`main`は`origin/main`へpush済み。直近commitは`80af718`（ローカルSync復旧訓練）、その前が`0b0fd24`（Git正本との定期照合・再送）。このメモ作成前の作業ツリーはclean。
- 本番DBはTurso Cloudの`juslagdb`（SQLite型、東京リージョン）。`.env.turso`はGit管理外・600で、URLと30日期限のトークンを保持する。値を表示・記録・commitしない。Actions Variable `JUSLAG_TURSO_DATABASE_URL`、Secret `JUSLAG_TURSO_AUTH_TOKEN`、Variable `JUSLAG_WRITE_TURSO=true`は設定済み。
- Gitの`data/reports/*.json`と`data/history.jsonl`が正本。2026-09-18にTursoへ既存51日分をバックフィルし、計52日分・54行を確認した。旧Pages、Slack、価格SQLiteキャッシュは維持。Tursoの障害は研究結果のGit保存を巻き戻さない。
- 日次Actionsのpublish後、`.github/workflows/turso-reconcile.yml`が平日09:30 JSTに最初のレポート日`2026-07-09`以降のGitとCloudを照合し、欠落・内容差分を最大10日分再送。手動実行は既定で監査のみ。差分があれば終了コード2。修復は新runを追加し、別接続からハッシュを読み戻す。`JUSLAG_WRITE_TURSO=false`でTursoジョブを停止できる。
- `pyturso==0.7.2`の公式`pull()`/`push()`と、公式`tursodb --sync-server`を使用。Gitとの内容比較、`run_id`の冪等化、再送制御のみJUSLAG固有コード。ブラウザにはトークンを渡さない。

## 直近の検証

- `scripts/ops/turso_recovery_drill.py --server-bin /tmp/turso_cli-x86_64-unknown-linux-gnu/tursodb`を使い捨てのローカルSyncサーバーで実行し、欠落補填、差分修復、サーバー停止中のpush失敗、復帰後の同一run再送、別クライアント読み戻し、重複なしがPASS。本番Cloudの行は変更していない。スクリプトはバイナリを`--server-bin`で渡すため、`/tmp`の実パスは消失し得る。
- この訓練で、ローカルcommit後にpushのみ失敗した場合の再送漏れを発見し修正。`repair_snapshots()`は既存runでもpushを再試行する。関連ユニットテストを追加。
- 全テスト`245 passed, 40 warnings`（既存Pandas4Warning）。Ruffと`git diff --check`も通過。push後の読み取り専用[Actions監査 #35313515646](https://github.com/yaziuma/JUSLAG/actions/runs/35313515646)は成功。Cloudの要修復は0日。
- 詳細は[実証記録](turso_actions_verification_20260918.md)と[運用手順](../turso_credentials.md)。
- 追加の[エクスポート検査](turso_export_audit_20260918.md)では、Cloudからの取得物3行をSQLite整合性・Gitハッシュ一致で確認した。Cloudへの再インポートは未実施。

## 次の作業

1. Turso使用量の監視・早期警告を設計・実装する。まず公式の利用量API/CLIとTurso側の標準通知機能の有無を調べ、現契約の上限と現在値を再取得する。`juslag-turso-usage` skillに従い、Cloud Syncの頻度・初回pull量・アラート先・停止条件を記録する。超過課金は無効だが、上限到達による停止はあり得る。固定の古い無料枠数値を前提にしない。
2. 定期照合の10回連続成功を記録する。これは時間経過を要するため、実行履歴をその都度確認する。ローカル復旧訓練は済んだが、本番Cloud障害からの実復旧、Cloud再インポート、PITRは未検証。
3. B0/B1の残件: ローカルSyncサーバーの`turso_sync_last_change_id`内部テーブル警告の原因・影響、Cloud復元、Viewerの認証方針。B2 Viewerはまだ未実装。DBトークンをPagesのJavaScriptへ埋め込まない。
4. 戦略トラックAの最優先はUS/JPの情報利用可能時刻の監査と、当日寄りgap確認後に同じ寄り値で約定できるという前提の検証。現行戦略は研究専用・実発注不可。全体の順序は[統合計画](../implementation_roadmap_20260918.md)。

## 再開時の確認

```bash
git status --short
git log -1 --oneline
gh run list --repo yaziuma/JUSLAG --workflow turso-reconcile.yml --limit 10
```

資格情報を読み込むコマンドは`docs/turso_credentials.md`を参照し、シェルの`set -x`を無効にする。Cloud監査は書き込みなしで`scripts/ops/turso_reconcile.py`を実行できる。Cloud修復を試す際は`JUSLAG_WRITE_TURSO=1`を明示し、事前にGit上の正本と対象日・修復件数を確認する。
