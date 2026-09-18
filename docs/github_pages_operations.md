# GitHub Pages 公開・簡易認証 運用手順書

- 作成日: 2026-09-15
- 対象リポジトリ: `yaziuma/JUSLAG`
- 公開URL: https://yaziuma.github.io/JUSLAG/
- ワークフロー: `.github/workflows/daily-juslag.yml`

## 1. 概要

日次リサーチ結果から静的サイトを生成し、StatiCryptで全HTMLを
パスワード保護してGitHub Pagesへ公開する。

認証はサーバー側ログインではなく、ブラウザ上でHTMLを復号する簡易認証である。
正しいパスワードを入力すると、設定により認証情報がブラウザへ30日間記憶される。

## 2. 前提条件

GitHub CLIが利用でき、対象リポジトリへ認証済みであることを確認する。

```bash
gh auth status
```

想定状態:

- Account: `yaziuma`
- Active account: `true`
- Git operations protocol: `ssh`
- Token scopeに `repo` が含まれる

リポジトリには次の設定が必要である。

| 名前 | 種別 | 用途 |
|---|---|---|
| `SITE_PASSWORD` | Actions Secret | StatiCryptの閲覧パスワード |
| `JUSLAG_SLACK_WEBHOOK` | Actions Secret | 日次処理結果のSlack通知 |
| `GEMINI_OAUTH_CREDS` | Actions Secret | LLM要約処理の認証情報 |
| `ENABLE_SITE_DEPLOY` | Actions Variable | `true`でPages公開を有効化 |
| `JUSLAG_BACKTEST_SETTINGS` | Actions Variable | 本番バックテスト設定JSON |

登録状況は次のコマンドで確認できる。Secretの値そのものは表示されない。

```bash
gh secret list
gh variable list
```

## 3. 閲覧パスワードの設定

SSH端末で次を実行する。

```bash
gh secret set SITE_PASSWORD
```

新しいパスワードを入力してEnterを押し、`Ctrl+D`で確定する。

パスワードはチャット、Issue、Actionsログ、Git、コマンド引数へ貼らない。
値が外部へ露出した場合は、その値を使用せず直ちに再設定する。

## 4. Slack Webhookの設定

Slack App管理画面を手元のブラウザで開く。

https://api.slack.com/apps

1. `Create New App`から対象Workspaceにアプリを作成する。
2. `Incoming Webhooks`を開く。
3. `Activate Incoming Webhooks`を有効にする。
4. `Add New Webhook to Workspace`を選択する。
5. 通知先チャンネルを選び、許可する。
6. SSH端末で次を実行し、発行されたURLを直接入力する。

```bash
gh secret set JUSLAG_SLACK_WEBHOOK
```

Webhook URLは認証情報である。外部へ露出した場合はSlack側でRevokeし、再発行する。

## 5. Pages公開の有効化

Actions Variableを有効にする。

```bash
gh variable set ENABLE_SITE_DEPLOY --body true
```

GitHubのリポジトリ設定で、`Settings`、`Pages`、`Build and deployment`の
Sourceが`GitHub Actions`になっていることを確認する。

## 6. Pagesだけを手動で再公開する

最新の`main`に保存済みのデータを使い、データの再コミット、LLM要約、
Slack通知を行わずにPagesを再公開する。

```bash
gh workflow run daily-juslag.yml --ref main \
  -f skip_llm=true \
  -f skip_slack=true \
  -f dry_run=true
```

起動したRunを確認する。

```bash
gh run list --workflow daily-juslag.yml --limit 1
```

表示されたRun IDを指定して完了まで監視する。

```bash
gh run watch RUN_ID --exit-status
```

成功時は、`research`と`site`の両ジョブが成功し、`site`内の次の処理も成功する。

- `Render static site`
- `Password-protect site (StatiCrypt)`
- `Upload Pages artifact`
- `Deploy Pages`

## 7. 通常の日次処理を手動実行する

データ取得、LLM要約、Slack通知、データコミット、Pages公開をすべて実行する。

```bash
gh workflow run daily-juslag.yml --ref main
```

同じ日の日次データがすでにコミット済みの場合、再生成結果との差分によって
`git pull --rebase`が競合する可能性がある。Pagesの再公開だけが目的なら、
前節の`dry_run=true`を使用する。

古い失敗Runの`rerun`は当時のコミットを起点にするため、同日データがすでに
`main`へ入っている場合は使用しない。最新`main`から新しい手動Runを起動する。

## 8. ローカルから認証を自動確認する

初回準備:

```bash
cp .env.local.example .env.local
chmod 600 .env.local
uv sync --extra dev
uv run playwright install chromium
```

`.env.local`へGitHub Secret `SITE_PASSWORD`と同じ値を設定する。

```dotenv
JUSLAG_SITE_PASSWORD=ここにパスワードを設定
JUSLAG_SITE_URL=https://yaziuma.github.io/JUSLAG/
```

認証確認を実行する。

```bash
uv run python scripts/ops/check_pages_auth.py
```

成功時:

```text
Pages authentication and remembered report navigation succeeded: https://yaziuma.github.io/JUSLAG/
```

`.env.local`はGit管理対象外である。実行スクリプトはパスワードをコマンド引数や
標準出力へ表示せず、認証フォームへ直接入力する。ブラウザでの初回認証時は
`Remember me`を選ぶ。同じ日本時間の日付に公開された全ページでは、ページ移動や
同日再デプロイ後も再入力不要となる。翌日の公開ではソルトが変わるため再認証する。

## 9. パスワード変更手順

1. `gh secret set SITE_PASSWORD`でGitHub Secretを更新する。
2. `.env.local`の`JUSLAG_SITE_PASSWORD`を同じ値へ更新する。
3. 「Pagesだけを手動で再公開する」の手順を実行する。
4. `check_pages_auth.py`で新しいパスワードの認証成功を確認する。
5. 古いパスワードで復号できないことを必要に応じて確認する。

Secret更新だけでは公開済みHTMLは変わらない。新しいパスワードを反映するには、
必ずPagesを再デプロイする。

## 10. トラブルシューティング

### 公開URLが404になる

`site`ジョブが未実行または失敗している。最新Runを確認し、Pagesだけを
`dry_run=true`で再公開する。

### `research`は成功したが`site`がスキップされる

`ENABLE_SITE_DEPLOY`が`true`か確認する。

```bash
gh variable list
```

### `SITE_PASSWORD is not set`で失敗する

Secret名が正確に`SITE_PASSWORD`であることを確認し、再設定する。

```bash
gh secret set SITE_PASSWORD
```

### ローカル確認で認証が完了しない

- `.env.local`のパスワードがGitHub Secretと同じか確認する。
- パスワード変更後にPagesを再デプロイしたか確認する。
- Chromiumが未導入なら`uv run playwright install chromium`を実行する。
- `JUSLAG_SITE_URL`が公開URLを指しているか確認する。

### `Commit and push results`で競合する

同日データを古いRunから再生成した可能性が高い。古いRunを再実行せず、
最新`main`から`dry_run=true`の新しい手動Runを起動する。

## 11. セキュリティ上の注意

- StatiCryptは静的HTMLのクライアント側暗号化であり、厳格なアクセス制御ではない。
- パスワードをソース、HTML、ログ、チャットへ記録しない。
- `.env.local`の権限は`600`にする。
- Webhook URLもパスワードと同様にSecretとして扱う。
- 漏えいが疑われる場合は、値をローテーションしてPagesを再デプロイする。
- 機密性の高い情報を公開サイトの成果物へ含めない。
