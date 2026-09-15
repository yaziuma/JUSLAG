# JUSLAG 実装状況・デプロイ準備状況 調査結果

- 調査日: 2026-09-15
- 対象リポジトリ: JUSLAG
調査観点: ユーザ目線の機能、実装状況、デプロイに必要な不足項目

## 1. 結論

JUSLAG は、日米業種リードラグ戦略の研究・日次判断・レポート化・Slack 通知・静的閲覧サイト生成までの主要機能が実装済みである。

GitHub Actions による日次バッチ実行、結果コミット、GitHub Pages への静的サイトデプロイ導線も実装されているため、閲覧用ダッシュボード付きの日次リサーチ運用としては、環境設定を整えればデプロイ可能な状態に近い。

一方で、証券会社 API への自動発注、約定確認、保有ポジション照合、実運用リスク管理などは未実装である。したがって現状の位置づけは「投資判断支援・研究レポート運用」であり、「完全自動売買システム」ではない。

## 2. 実装済み機能

### 2.1 戦略コア

- 米国 11 業種 ETF と日本 TOPIX-17 業種 ETF を対象にしたデータ処理
- yfinance と SQLite キャッシュを使った価格取得
- raw / adjusted の価格モード分離
- US Close-to-Close リターン、JP Close-to-Close リターン、JP Open-to-Close リターンの生成
- 事前部分空間 `V0` の構築
- 長期相関からのターゲット行列 `C0` 構築
- 部分空間正則化 PCA による日本業種シグナル生成

主な実装箇所:

- `src/juslag/data_loader.py`
- `src/juslag/prior.py`
- `src/juslag/model.py`
- `src/juslag/signal.py`

### 2.2 日次投資判断

- 最新データを使った日次シグナル生成
- 各日本業種 ETF の `LONG` / `SHORT` / `neutral` 判定
- 翌営業日の JP 執行対象日計算
- LONG / SHORT 候補数、採用数、除外リストの出力
- シグナル閾値による採用・除外判定
- データ鮮度、カレンダー信頼性、利用可能銘柄数のチェック
- 取引可否判定と見送り理由分類
- 発注 JSON ペイロードの生成ロジック

主な実装箇所:

- `src/juslag/services/daily_signal.py`
- `src/juslag/signal.py`

### 2.3 バックテスト

- 指定期間での戦略バックテスト
- Momentum、Plain PCA、Subspace-Regularized PCA の比較
- Gross、コスト控除後、税引後の成績算出
- 手数料、スリッページ、借株料の反映
- 空売り可否、空売り不可銘柄の制約
- 税モデルの適用
- パフォーマンス時系列、ドローダウン、コスト内訳の出力
- Judge による総合評価

主な実装箇所:

- `src/juslag/services/backtest.py`
- `src/juslag/portfolio.py`
- `src/juslag/metrics.py`
- `src/juslag/judge.py`

### 2.4 メタ戦略ルール

通常のシグナル売買に加えて、局面や寄り付きギャップに応じたメタ戦略ルールを選択できる。

実装済みルール:

- `rule_406`
- `rule_406_no_flip`
- `rule_399`
- `rule_13`
- `rule_87`
- `rule_1357`
- `rolling3_selector`

主な実装箇所:

- `src/juslag/strategies/`
- `src/juslag/strategies/registry.py`

### 2.5 日次リサーチバッチ

日次バッチでは、以下の処理が一括実行される。

1. データ取得
2. データステータス評価
3. 本番設定でのバックテスト
4. 本日のシグナル計算
5. 戦略履歴の保存
6. Slack フォールバック文面生成
7. 日次レポート JSON 出力
8. 監査用 raw / processed データ保存

主な出力:

- `data/reports/YYYY-MM-DD.json`
- `data/history.jsonl`
- `data/strategy_history.jsonl`
- `data/raw/YYYY-MM-DD/`
- `data/processed/YYYY-MM-DD/`

主な実装箇所:

- `scripts/ops/daily_research.py`
- `scripts/ops/daily_research.sh`

### 2.6 Slack 通知・LLM 要約

- 日次レポート JSON から Slack 投稿用サマリーを生成
- LLM 要約に失敗した場合はフォールバック文面を使用
- Slack 通知失敗時もデータ保存・コミットは維持する設計
- GitHub Actions 失敗時の Slack 失敗通知も実装済み

主な実装箇所:

- `scripts/ops/daily_research.sh`
- `src/juslag/services/notify.py`

### 2.7 静的閲覧サイト

- `data/history.jsonl` と `data/reports/*.json` から静的 HTML を生成
- 最新サマリー表示
- 日次履歴一覧
- 執行 / 見送りフィルタ
- レジーム、LONG / SHORT、Judge スコア表示
- 日次詳細ページ
- Bootstrap + Alpine.js によるビルド不要の静的サイト

主な実装箇所:

- `scripts/ops/render_pages.py`
- `src/juslag/services/site.py`

### 2.8 GitHub Actions

`.github/workflows/daily-juslag.yml` に以下が実装済み。

- 平日 JST 8:00 のスケジュール実行
- 手動実行
- `uv sync --frozen` による依存関係インストール
- `config/app.ci.yaml` から `config/app.yaml` を作成
- 価格キャッシュ DB の復元
- 日次リサーチバッチ実行
- 結果を `data/` にコミット・プッシュ
- GitHub Pages 用サイト生成
- StatiCrypt による HTML パスワード保護
- GitHub Pages へのデプロイ

## 3. テスト状況

調査時点で以下を確認済み。

```text
212 passed, 40 warnings in 110.48s
```

警告は `src/juslag/data_loader.py` の `pd.concat(..., axis=1)` に対する Pandas 4 系の将来互換 warning であり、現時点のテスト失敗ではない。

## 4. デプロイに必要な設定

### 4.1 必須設定

GitHub Pages への閲覧サイトデプロイを行うには、以下が必要。

- GitHub Actions の有効化
- Repository Settings -> Pages -> Source を `GitHub Actions` に設定
- GitHub Variable `JUSLAG_BACKTEST_SETTINGS`
- GitHub Variable `ENABLE_SITE_DEPLOY=true`
- GitHub Secret `SITE_PASSWORD`

`JUSLAG_BACKTEST_SETTINGS` は本番バックテスト設定であり、未設定の場合は `load_production_backtest_params()` がエラーを送出する。日次バッチを本番運用するうえで最初に設定すべき項目である。

想定形式:

```json
{
  "name": "production",
  "form": {
    "sample_start": "2018-07-01",
    "sample_end": "2025-12-31",
    "pretrain_end": "2021-12-31",
    "window_l": 60,
    "k_factors": 3,
    "lambda_reg": 0.9,
    "quantile_q": 0.3,
    "strategy_rule_id": "rule_406_no_flip"
  }
}
```

### 4.2 任意だが推奨される設定

Slack 通知を使う場合:

- GitHub Secret `JUSLAG_SLACK_WEBHOOK`

LLM 要約を使う場合:

- GitHub Secret `GEMINI_OAUTH_CREDS`

LLM 要約を使わない場合は、GitHub Actions の手動実行で `skip_llm=true` を指定できる。ただしスケジュール実行では通常 LLM 導線が有効になるため、認証情報を用意するか、workflow 側で LLM をデフォルト skip にする運用判断が必要。

## 5. デプロイ前に不足しているもの

### 5.1 環境設定

コード上のデプロイ導線はあるが、以下の外部設定が必要。

- GitHub Variables
  - `JUSLAG_BACKTEST_SETTINGS`
  - `ENABLE_SITE_DEPLOY`
- GitHub Secrets
  - `SITE_PASSWORD`
  - `JUSLAG_SLACK_WEBHOOK`
  - `GEMINI_OAUTH_CREDS`
- GitHub Pages 設定
- 必要に応じた repository permissions の確認

### 5.2 実売買運用に必要な機能

現状は投資判断支援・研究レポート運用までであり、以下は未実装。

- 証券会社 API への自動発注
- 約定確認
- 保有ポジション照合
- 現金残高・信用余力チェック
- 発注前の最終リスクチェック
- 日次損失上限、建玉上限、銘柄別上限
- 発注失敗時のリトライ・通知
- 実約定ベースの PnL 管理
- 手動承認フロー

### 5.3 認証・公開範囲

GitHub Pages の閲覧サイトは StatiCrypt による HTML 単位のパスワード保護である。簡易な共有用途には十分だが、ユーザ別権限、監査ログ、SSO、多要素認証が必要な用途では別のホスティング基盤または認証基盤が必要。

### 5.4 外部依存

以下の外部サービス・ネットワーク依存がある。

- yfinance
- Kenneth French Data Library
- GitHub Actions
- GitHub Pages
- Slack Incoming Webhook
- agy / Gemini OAuth
- npx / staticrypt
- Bootstrap CDN
- Alpine.js CDN

完全に閉じた環境や社内ネットワーク制限下で運用する場合は、依存先の許可または代替実装が必要。

### 5.5 将来互換性

Pandas 4 系に向けて、`data_loader.py` の `pd.concat` に `sort=` を明示する修正が望ましい。現時点では warning のみで、デプロイ阻害要因ではない。

## 6. デプロイ可否判定

### 6.1 日次リサーチ・閲覧サイトとしてのデプロイ

判定: 可能

理由:

- 日次バッチ実装済み
- GitHub Actions 実装済み
- GitHub Pages デプロイ実装済み
- パスワード保護実装済み
- テスト全通過
- 必要な不足は主に Secrets / Variables / Pages 設定

### 6.2 実売買システムとしてのデプロイ

判定: 不足あり

理由:

- 自動発注が未実装
- 約定・ポジション・残高の照合が未実装
- 実運用リスク管理が未実装
- 手動承認またはフェイルセーフ導線が未整備

## 7. 推奨デプロイ手順

1. GitHub Pages の Source を `GitHub Actions` に設定する。
2. `SITE_PASSWORD` を GitHub Secret に登録する。
3. `JUSLAG_BACKTEST_SETTINGS` を GitHub Variable に登録する。
4. Slack 通知を使う場合は `JUSLAG_SLACK_WEBHOOK` を登録する。
5. LLM 要約を使う場合は `GEMINI_OAUTH_CREDS` を登録する。
6. `ENABLE_SITE_DEPLOY=true` を GitHub Variable に登録する。
7. GitHub Actions の `workflow_dispatch` で `dry_run=true`、必要に応じて `skip_llm=true` / `skip_slack=true` で試験実行する。
8. dry run のログと生成レポートを確認する。
9. `dry_run=false` で本実行し、`data/` のコミットと Pages デプロイを確認する。
10. Slack 通知、サイト表示、パスワード保護、日次履歴表示を確認する。

## 8. 優先度付き残タスク

### P0: デプロイ前必須

- `JUSLAG_BACKTEST_SETTINGS` の本番値を確定
- `SITE_PASSWORD` の登録
- GitHub Pages 設定
- `ENABLE_SITE_DEPLOY=true` の登録
- 初回手動実行で日次バッチとサイトデプロイを確認

### P1: 運用品質向上

- Slack Webhook の登録
- LLM 要約の認証情報登録、または LLM skip 運用への変更
- Pandas 4 warning の解消
- GitHub Actions 失敗時の運用手順整理
- 日次レポートの保存期間・肥大化対策

### P2: 実売買へ進める場合

- 証券会社 API 連携
- 発注前承認フロー
- 約定・ポジション照合
- 残高・信用余力チェック
- リスク上限
- 実約定ベースの損益管理
- 緊急停止スイッチ

## 9. 総括

JUSLAG は、研究用 PoC から日次リサーチ運用ツールへ移行するための主要部品が揃っている。現時点で最も近いデプロイ形態は、GitHub Actions と GitHub Pages を使った「日次シグナル・バックテスト・レポート閲覧」基盤である。

本番デプロイの主な残作業はコード実装ではなく、GitHub Variables / Secrets / Pages の設定である。ただし、実売買まで自動化する場合は、発注・約定・ポジション・リスク管理の実装が別途必要である。
