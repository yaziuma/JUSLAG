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

`pyturso==0.7.2`を`pyproject.toml`の`turso` extraとして固定した。ローカルでは次のように使う。書込は`JUSLAG_WRITE_TURSO=1`を明示したときだけ有効。`read`は指定日の最新runをJSONに書き出し、出力ファイルは600で新規作成する。

```bash
set -a; source .env.turso; set +a
uv sync --frozen --extra turso
JUSLAG_WRITE_TURSO=1 uv run --frozen --extra turso python scripts/ops/turso_daily.py publish --report data/reports/2026-09-18.json
uv run --frozen --extra turso python scripts/ops/turso_daily.py read --date 2026-09-18 --out /tmp/juslag-readback.json
```

Actionsの`daily-juslag.yml`は`JUSLAG_WRITE_TURSO`リポジトリ変数が`true`の時だけ、研究結果のGit保存後に独立したTursoジョブを実行する。URLは`JUSLAG_TURSO_DATABASE_URL`変数、書込トークンは`JUSLAG_TURSO_AUTH_TOKEN` Secretを使う。研究・Git・Pages・SlackはTursoジョブの失敗から独立している。手動の`turso-smoke.yml`では、指定した既存日付をGitHub Actionsから書き込み・読み戻して照合できる。トークンは30日で期限切れとなるため、期限前に更新してActions Secretも同時更新する。

保存形式は`juslag_daily_snapshots`の1行にレポートJSON、確定要約、LLM状態、生成時刻、コードSHA、内容SHA-256を格納する。同じ`run_id`で内容が変わった場合は上書きせず失敗する。同日再実行は別runとして残り、読取ではその日の最新公開runを返す。ファイルが正本であり、Turso失敗時はGit上の結果を再確認してから手動再送する。`turso-smoke`は既存データで読書きするため、本番の次回予定日を指定しない。

Sync方式ではActionsの一時DBが毎回Cloudから`pull()`する。これは履歴が増えるほど初回同期量を消費する。現時点の小規模実測は`docs/reports/turso_b0_poc_20260918.md`に記録。運用開始後は`Turso db inspect`で同期量を追い、DB全体の増加によって月間3 GB枠に近づく前に直接書込方式か保持期間を再評価する。ブラウザからのCloud直接接続は行わない。
