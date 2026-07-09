# scripts 整理方針

`scripts/` 直下には実行ファイルを置かず、用途別ディレクトリに分ける。
一時研究・検証済みスクリプトはコミットせず削除する（必要になれば git 履歴から復元する）。

## 本番・運用系: `scripts/ops/`

| ファイル | 用途 | 実行例 |
|---|---|---|
| `daily_research.py` | 日次リサーチバッチ本体。データ取込、バックテスト、日次シグナル、履歴保存、`data/reports/YYYY-MM-DD.json` 生成をライブラリ直接呼び出しで実行する。 | `uv run python scripts/ops/daily_research.py` |
| `daily_research.sh` | GitHub Actions 用オーケストレーション。前回サマリー読込 → `daily_research.py` → agy によるLLM要約（失敗時は生レポートへフォールバック）→ `data/history.jsonl` 追記 → Slack通知。 | `bash scripts/ops/daily_research.sh` |
| `render_pages.py` | `data/history.jsonl` と `data/reports/*.json` から閲覧用静的HTMLを `_site/` に生成する。 | `uv run python scripts/ops/render_pages.py --out _site` |

`daily_research.sh` は `JUSLAG_SLACK_WEBHOOK` / `JUSLAG_BACKTEST_SETTINGS_JSON` / `LLM_CMD` などを環境変数から読む。Webhook URLやAPIキーをコードに直書きしない。

## データ保守系: `scripts/data/`

| ファイル | 用途 |
|---|---|
| `fetch_factor_data.py` | Kenneth French Data Library から日本FF3/WMLを取得し、`data/external/factors/normalized/` に保存する。 |
| `fetch_corporate_actions.py` | yfinance から米国・日本ETFのdividend/splitを取得し、`data/external/actions/` に保存する。 |

## 正式レポート系: `scripts/reports/`

| ファイル | 用途 |
|---|---|
| `build_period_quant_output.py` | 複数期間×戦略の定量出力。日次・月次・年次・期間サマリ・ベースライン比較CSVとMarkdownを生成する。 |
