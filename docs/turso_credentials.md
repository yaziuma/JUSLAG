# Turso資格情報の設定

JUSLAGのTurso PoC用に、ローカルの書込可能なDBトークンを作る手順。現在のバッチ・サイトはこのファイルをまだ読み込まない。トークンをチャット、Git、ブラウザのJavaScriptへ貼らない。

1. SSH端末でTurso CLIの認証を済ませる。ブラウザを開けない環境では`turso auth login --headless`を使う。`turso auth whoami`がログイン済みのユーザーを表示することを確認する。CLIは未ログイン時も終了コード0でエラー文を出す場合があるため、終了コードだけで判定しない。
2. リポジトリのルートから`bash scripts/ops/setup_turso_credentials.sh <database-name>`を実行する。CLIがDB URLを取得し、有効期限30日のトークンを発行して、`0600`の`.env.turso`へ保存する。トークンそのものは表示しない。
3. 内容を端末へ出さずに存在と権限を確認する: `stat -c '%a %n' .env.turso`。更新時は同コマンドの末尾に`--replace`を付ける。更新後は旧トークンの失効と、他に配布済みの資格情報の更新を別途確認する。

2026-09-18の初回スクリプトにはCLIエラー文を値として保存する不具合があった。初回実行で作成した`.env.turso`は無効なので、ログイン後に`bash scripts/ops/setup_turso_credentials.sh juslagdb --replace`で再作成する。修正版はURL・トークン形式が不正なら保存しない。

ローカルのシェルで使う場合は`set -a; source .env.turso; set +a`。`set -x`を有効にしたまま読み込まない。ファイルは`.gitignore`対象で、見本の[`.env.turso.example`](../.env.turso.example)に実値は入れない。

将来GitHub Actionsから書き込む段階では、URLとトークンを別々に設定する。次のコマンドは秘密値をコマンドライン引数に載せず、トークンを標準入力で渡す。GitHub CLIの認証と対象リポジトリを先に確認する。

```bash
set +x
set -a; source .env.turso; set +a
printf '%s' "$JUSLAG_TURSO_AUTH_TOKEN" | gh secret set JUSLAG_TURSO_AUTH_TOKEN --repo yaziuma/JUSLAG
gh variable set JUSLAG_TURSO_DATABASE_URL --body "$JUSLAG_TURSO_DATABASE_URL" --repo yaziuma/JUSLAG
unset JUSLAG_TURSO_AUTH_TOKEN JUSLAG_TURSO_DATABASE_URL
```

ブラウザ閲覧にはこの書込トークンを使わず、認証方式の決定後に権限を分離する。

## 日次スナップショットの読み書き

`libsql==0.1.11`（日次のCloud直接接続）と`pyturso==0.7.2`（ローカルSync検証）を`turso` extraに固定した。ローカルでは次のように使う。書込は`JUSLAG_WRITE_TURSO=1`を明示したときだけ有効。`read`は指定日の最新runをJSONに書き出し、出力ファイルは600で新規作成する。

```bash
set -a; source .env.turso; set +a
uv sync --frozen --extra turso
JUSLAG_WRITE_TURSO=1 uv run --frozen --extra turso python scripts/ops/turso_daily.py publish --report data/reports/2026-09-18.json
uv run --frozen --extra turso python scripts/ops/turso_daily.py read --date 2026-09-18 --out /tmp/juslag-readback.json
```

Actionsの`daily-juslag.yml`は`JUSLAG_WRITE_TURSO`リポジトリ変数が`true`の時だけ、研究結果のGit保存後に独立したTursoジョブを実行する。URLは`JUSLAG_TURSO_DATABASE_URL`変数、書込トークンは`JUSLAG_TURSO_AUTH_TOKEN` Secretを使う。研究・Git・Pages・SlackはTursoジョブの失敗から独立している。手動の`turso-smoke.yml`では、指定した既存日付をGitHub Actionsから書き込み・読み戻して照合できる。トークンは30日で期限切れとなるため、期限前に更新してActions Secretも同時更新する。

2026-09-18時点で`JUSLAG_WRITE_TURSO=true`を設定し、[日次Actions実行](https://github.com/yaziuma/JUSLAG/actions/runs/35310809472)で同期を確認した。問題が起きた場合は`gh variable set JUSLAG_WRITE_TURSO --body false --repo yaziuma/JUSLAG`で次回以降のTursoジョブだけ止める。Git・Pages・Slack経路は継続する。

保存形式は`juslag_daily_snapshots`の1行にレポートJSON、確定要約、LLM状態、生成時刻、コードSHA、内容SHA-256を格納する。同じ`run_id`で内容が変わった場合は上書きせず失敗する。同日再実行は別runとして残り、読取ではその日の最新公開runを返す。ファイルが正本であり、Turso失敗時はGit上の結果を次回の定期照合で再送する。`turso-smoke`は既存データで読書きするため、本番の次回予定日を指定しない。

`turso-reconcile.yml`は平日09:30 JSTに、Git上の確定レポートとCloudの同日最新runを照合し、欠落・差分だけを最大10日分再送する。既存51日分のバックフィルが完了したため、既定の開始日は最初のレポート日`2026-07-09`。上限超過・読取不能・Cloud読み戻し不一致は失敗としてSlackに通知する。次回定期実行または手動再実行で未修復分を再試行する。修復は既存行を上書きせず新runを追加する。修復runの`source_commit`は照合ワークフローのcommitであり、元レポート生成時のcommitではない。

GitHub scheduleの遅延・未生成に備えたローカル補助系は、`bash scripts/ops/install_turso_reconcile_timer.sh`で導入する。平日10:15 JSTに`origin/main`をfetchし、確定済みの`data/reports`と`data/history.jsonl`だけを一時領域へ展開してCloudと照合する。作業ツリーの内容は監査対象にせず、Cloud修復もしない。不一致・認証期限切れ・ネットワーク障害はserviceを失敗させてjournalへ残す。

```bash
systemctl --user status juslag-turso-reconcile.timer --no-pager
journalctl --user -u juslag-turso-reconcile.service --no-pager -n 200
```

手動Actions実行は既定で照合のみ（差分があれば終了コード2）。`repair=true`を選ぶと再送する。ローカルでは下記の通り。未投入の多数の日付を修復する場合は事前に監査で件数を確認し、必要なら`--max-repairs`を指定する。

```bash
set -a; source .env.turso; set +a
uv run --frozen --extra turso python scripts/ops/turso_reconcile.py
JUSLAG_WRITE_TURSO=1 uv run --frozen --extra turso python scripts/ops/turso_reconcile.py --repair
```

ワークフロー停止は`JUSLAG_WRITE_TURSO=false`。日次publish・照合・価格差分更新は公式`libsql`の直接SQL接続を使い、別接続で読み戻す。全件移行に使った旧Sync方式は実証用として残すが、価格データ増加後の日次実行では初回pullの使用量が大きいため使わない。詳細は[全データ移行結果](reports/turso_full_migration_20260918.md)。

本番Cloudを変更せずに復旧経路を試すには、公式`tursodb`実行ファイルを指定して`uv run --frozen --extra turso python scripts/ops/turso_recovery_drill.py --server-bin /path/to/tursodb`を実行する。スクリプトは一時DB・localhostのSyncサーバーを作り、欠落、差分、切断中のpush失敗、復帰後の再送を検証して終了する。

価格キャッシュを含むCloud移行後、旧Sync方式の初回pull量が増えたため、日次経路は直接書込方式へ変更した。`turso plan show`で月間使用量を追い、通常の日次実行でEmbedded Syncsが増えないことを確認する。ブラウザからのCloud直接接続は行わない。

2026-09-18の現契約・使用量、暫定の監視閾値と停止条件は[利用量レビュー](reports/turso_usage_review_20260918.md)に記録した。枠の数値は固定せず、`turso plan show`で再確認する。利用量閾値の自動通知は未実装であり、照合失敗時のSlack通知と区別する。
