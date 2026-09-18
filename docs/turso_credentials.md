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

現時点ではworkflowにTurso書込処理がないため、Secretsを設定しても二重書きは始まらない。ブラウザ閲覧にはこの書込トークンを使わず、認証方式の決定後に権限を分離する。
