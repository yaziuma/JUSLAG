# JUSLAG

日米業種リードラグ戦略（Subspace-Regularized PCA）の研究用実装です。  
本リポジトリは、PoC単一スクリプトを公開レビュー可能なPythonプロジェクト構成へ段階移行することを目的に整理されています。

## 1. プロジェクト概要

- **対象**: 米国11業種ETF（説明変数）と日本TOPIX-17業種ETF（投資対象）
- **狙い**: 米国終値情報から翌営業日の日本業種リターンを予測
- **位置づけ**: 研究用・検証用（実運用保証なし）

## 2. 戦略概要

1. 米国 Close-to-Close リターンと日本 Close-to-Close リターンを結合
2. 事前部分空間 `V0`（グローバル / 国スプレッド / シクリカル）を構築
3. 長期相関からターゲット行列 `C0` を作成
4. 部分空間正則化付きPCAで日本側シグナルを推定
5. 上位分位をLONG、下位分位をSHORT（等ウェイト）で翌営業日 Open-to-Close を評価

## 3. 現在の実装範囲

- モジュール分割（`src/juslag/`、オーケストレーションは `src/juslag/services/`）
- paper_like / daily のモード分離
- 静的閲覧サイト / 日次シグナル / バックテスト / Judge / レポート出力
- 日次リサーチバッチ（GitHub Actions。データ取込、バックテスト、日次シグナル、履歴保存、LLM要約、Slack通知、結果のリポジトリ保存）
- 最低限テスト（prior / model / portfolio / metrics など）

日次バッチの全体設計は `docs/daily_research_batch_architecture.md` を参照してください。

## 4. 未実装・注意点

- 売買コスト・スリッページ未考慮の古い検証経路が一部残っています
- 借株料・空売り実務制約は設定・評価経路により扱いが異なります
- 祝日・時差カレンダー整列は運用経路とlegacy経路で差があります
- ETF可用性制約のため2018年以降を対象とした paper-like backtest（論文の厳密再現ではない）

## 5. ディレクトリ構成

```text
JUSLAG/
├─ README.md
├─ pyproject.toml
├─ .github/
│  └─ workflows/  # 日次バッチ（daily-juslag.yml）
├─ docs/
│  ├─ daily_research_batch_architecture.md
│  └─ scripts.md
├─ src/
│  └─ juslag/
│     └─ services/  # 日次バッチ・静的サイト生成共用のオーケストレーション層
├─ scripts/
│  ├─ ops/        # 本番・運用導線（日次バッチ、静的サイト生成 ほか）
│  ├─ data/       # 外部データ取得・正規化
│  └─ reports/    # 正式レポート生成
├─ data/
│  ├─ raw/        # 日次バッチの取得データ監査ログ（日付別）
│  ├─ processed/  # 日次バッチの加工済みデータ（日付別）
│  ├─ reports/    # 日次レポートJSON（YYYY-MM-DD.json）
│  └─ history.jsonl  # LLM日次サマリー履歴
└─ tests/
```

`scripts/` の詳細は `docs/scripts.md` を参照してください。

## 6. セットアップ

```bash
uv sync --extra dev
```

## 7. 実行方法

`config/app.yaml` と `config/logging.yaml` をそれぞれ `config/app.example.yaml` / `config/logging.example.yaml` から作成して使ってください。実ファイルはコミットしません。

### 日次リサーチバッチ

平日 JST 8:00 に GitHub Actions（`.github/workflows/daily-juslag.yml`）が自動実行します。ローカルで試す場合:

```bash
# バッチ本体のみ（データ取込→バックテスト→日次シグナル→data/reports/YYYY-MM-DD.json）
uv run python scripts/ops/daily_research.py

# LLM要約・Slack通知込みのフル実行（要 agy / JUSLAG_SLACK_WEBHOOK）
export JUSLAG_SLACK_WEBHOOK='...'
bash scripts/ops/daily_research.sh

# 通知なしのドライラン
SKIP_LLM=1 SKIP_SLACK=1 bash scripts/ops/daily_research.sh
```

GitHub Actions 側で必要な Secrets / Variables:

| 名前 | 種別 | 内容 |
|---|---|---|
| `GEMINI_OAUTH_CREDS` | Secret | `~/.gemini/oauth_creds.json` の中身（agy のOAuth認証） |
| `JUSLAG_SLACK_WEBHOOK` | Secret | Slack Incoming Webhook URL |
| `SITE_PASSWORD` | Secret | 閲覧サイトのパスワード（StatiCrypt によるページ暗号化に使用） |
| `JUSLAG_BACKTEST_SETTINGS` | Variable | 本番バックテスト設定JSON（`{"name": ..., "form": {BacktestParamsのフィールド}}`）。JSONを直接編集して `gh variable set JUSLAG_BACKTEST_SETTINGS < setting.json` で登録・更新する |
| `ENABLE_SITE_DEPLOY` | Variable | `true` で閲覧サイトのGitHub Pagesデプロイを有効化 |

### 閲覧サイト（GitHub Pages + パスワード保護）

日次バッチの `site` ジョブが `data/` の結果から静的ダッシュボード（Bootstrap + Alpine.js、旧WebUIの見た目を踏襲）を生成し、
**StatiCrypt で全HTMLをパスワード暗号化**したうえで GitHub Pages にデプロイします。
閲覧時はパスワードを一度入力すれば30日間記憶されます。

有効化手順:

1. `gh secret set SITE_PASSWORD`（閲覧パスワードを登録）
2. リポジトリ Settings → Pages → Source を **GitHub Actions** にする
   （private リポジトリの Pages は Pro 以上のプランが必要）
3. `gh variable set ENABLE_SITE_DEPLOY --body true`

ローカルでのプレビュー:

```bash
uv run python scripts/ops/render_pages.py --out _site
python3 -m http.server -d _site 8080  # http://localhost:8080
```

## 8. 論文との対応関係（現時点）

参照論文: 「部分空間正則化付き主成分分析を用いた日米業種リードラグ投資」  
（著作権保護のためPDF本体はリポジトリに含めていません。タイトルで検索して入手してください）

- 部分空間正則化付きPCAのコアロジック: 実装済み
- ベースライン比較: 簡易Momentum / Plain PCAを実装
- 実運用要件（コスト、執行制約）: 日次バッチ / 運用ジョブ側で拡張中

## 9. 注意事項

- 本コードは**研究用 / PoC**です
- 実運用収益を保証しません
- 秘密情報やWebhook URLはコミットしないでください

## Legacyについて

`lead_lag_strategy.py` は互換性確保のため当面残しています。  
旧CLI（`scripts/legacy/`）と検証済み一時スクリプト（`scripts/archive/`）は削除しました。必要になった場合は git 履歴から復元してください。新規開発は `src/juslag/`、`scripts/ops/`、`scripts/reports/` 側を優先してください。
