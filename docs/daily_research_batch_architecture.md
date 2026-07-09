# JUSLAG日次リサーチバッチ 修正後構成・動作概要

## 1. 目的

JUSLAGのクオンツ分析処理を日次で自動実行し、取得データ・分析結果・LLM要約をリポジトリに保存する。
あわせて、当日の投資判断サマリーをSlackへ通知し、必要に応じてGitHub Pages上で過去結果を閲覧できるようにする。

本構成では、GitHub Pagesは処理実行基盤としては使用しない。
Python処理、JUSLAG実行、データ取得、LLM要約、Slack通知はGitHub Actions上で実行する。

---

## 2. 全体構成

```text
GitHub Actions
  ├─ 定期起動 / 手動起動
  ├─ JUSLAG日次ジョブ実行
  ├─ 取得データ保存
  ├─ 日次レポート生成
  ├─ agy / LLM による要約
  ├─ history.jsonl へ追記
  ├─ Slack通知
  └─ 生成物をリポジトリへcommit / push

GitHub Repository
  ├─ ソースコード
  ├─ 取得データ
  ├─ 分析結果
  ├─ 要約履歴
  └─ GitHub Pages用HTML

GitHub Pages
  └─ 静的な結果閲覧ページ

Slack
  └─ 当日サマリー通知
```

---

## 3. 役割分担

| 要素                | 役割                           |
| ----------------- | ---------------------------- |
| GitHub Actions    | 日次バッチの実行基盤                   |
| JUSLAG            | データ取得、シグナル生成、バックテスト、日次分析     |
| agy / LLM         | システム出力を投資判断向けに要約             |
| GitHub Repository | コード、取得データ、分析結果、要約履歴の保存先      |
| GitHub Pages      | 結果を閲覧するための静的ページ              |
| Slack             | 当日結果の通知先                     |
| GitHub Secrets    | APIキー、Slack Webhookなどの秘匿情報管理 |

---

## 4. リポジトリ構成案

```text
repository/
├─ .github/
│  └─ workflows/
│     └─ daily-juslag.yml
│
├─ scripts/
│  ├─ daily_research.sh
│  ├─ daily_morning_job.py
│  └─ render_pages.py
│
├─ src/
│  └─ juslag/
│
├─ data/
│  ├─ raw/
│  │  └─ yyyy-mm-dd/
│  │     └─ 取得データ
│  │
│  ├─ processed/
│  │  └─ yyyy-mm-dd/
│  │     └─ 加工済みデータ
│  │
│  ├─ reports/
│  │  └─ yyyy-mm-dd.json
│  │
│  └─ history.jsonl
│
├─ docs/
│  └─ index.html
│
├─ requirements.txt
└─ README.md
```

---

## 5. 日次処理の流れ

### 5.1 起動

GitHub Actionsのcronにより、平日朝などの指定時刻に自動実行する。
必要に応じて `workflow_dispatch` により手動実行も可能にする。

```text
定期実行
  または
手動実行
  ↓
GitHub Actions起動
```

---

### 5.2 環境準備

Actions上で以下を準備する。

* Python環境
* Python依存ライブラリ
* `jq`
* agy
* JUSLAG実行に必要な環境変数
* Slack Webhook
* 各種APIキー

秘匿情報はGitHub Secretsに保存し、リポジトリには直接書かない。

---

### 5.3 前回サマリーの読み込み

`data/history.jsonl` の最終行から、前回のサマリーを取得する。

```text
data/history.jsonl
  ↓
直近1件のsummaryを取得
  ↓
今回のLLM要約プロンプトに利用
```

これにより、前回からの変化を踏まえた要約が可能になる。

---

### 5.4 JUSLAG日次ジョブの実行

`scripts/daily_morning_job.py` を実行し、以下を生成する。

* 当日の取得データ
* レジーム判定
* シグナル判定
* メタ戦略の点灯状況
* バックテスト結果
* 日次レポート

実行結果は標準出力として受け取り、同時にファイルとしても保存する。

---

### 5.5 取得データの保存

取得データはリポジトリ内に保存する。

保存先例:

```text
data/raw/yyyy-mm-dd/
data/processed/yyyy-mm-dd/
data/reports/yyyy-mm-dd.json
```

保存する主なデータは以下。

| 種別      | 保存先例                           | 内容             |
| ------- | ------------------------------ | -------------- |
| 生データ    | `data/raw/yyyy-mm-dd/`         | API等から取得した元データ |
| 加工済みデータ | `data/processed/yyyy-mm-dd/`   | 分析用に整形したデータ    |
| 日次レポート  | `data/reports/yyyy-mm-dd.json` | JUSLAGの分析結果    |
| 要約履歴    | `data/history.jsonl`           | LLMが生成した日次サマリー |

取得データをリポジトリに保存することで、Gitの履歴がそのまま監査ログになる。
いつ、どのデータで、どのような判断が出たかを後から追跡できる。

---

### 5.6 LLMによる要約

JUSLAGの日次出力と前回サマリーをagyに渡し、Slack向けの要約を生成する。

要約では特に以下を重視する。

* 前回からの変化
* レジーム判定の変化
* 重要シグナルの点灯
* Rule 406などの注目メタ戦略
* LONG / SHORTの変化
* 判断上の注意点

---

### 5.7 要約結果の保存

LLMが生成した要約は `data/history.jsonl` に追記する。

形式例:

```json
{"date":"2026-07-08T23:30:00Z","summary":"本日のサマリー..."}
```

JSONL形式にすることで、追記処理が単純になり、過去履歴の読み込みも容易になる。

---

### 5.8 Slack通知

生成した要約をSlackへ送信する。

通知内容は以下のような構成にする。

```text
🤖 本日のJUSLAG定期リサーチ結果

- レジーム判定
- 主要シグナル
- 注目戦略
- 前回からの変化
- 注意点
```

Slack通知により、リポジトリやPagesを見に行かなくても当日の判断概要を確認できる。

---

### 5.9 GitHub Pages用HTML生成

必要に応じて、`data/history.jsonl` や `data/reports/` から `docs/index.html` を生成する。

GitHub Pagesでは以下を閲覧できるようにする。

* 最新サマリー
* 過去サマリー一覧
* 日付別レポート
* レジーム推移
* シグナル履歴

GitHub Pagesは静的HTMLの表示のみを担当し、Python処理やデータ取得は行わない。

---

### 5.10 変更内容のcommit / push

処理完了後、以下の生成物をGitにcommitする。

```text
data/raw/
data/processed/
data/reports/
data/history.jsonl
docs/index.html
```

これにより、次回実行時にも前回データを参照できる。

---

## 6. エラー時の動作

### 6.1 JUSLAG実行失敗

JUSLAG本体の処理に失敗した場合は、ワークフローを失敗扱いにする。
この場合、誤った分析結果を保存・通知しない。

必要に応じて、Slackへ失敗通知のみ送る。

---

### 6.2 LLM要約失敗

JUSLAG実行は成功しているがagy / LLM要約に失敗した場合は、処理全体を即停止させない。

代替動作として、JUSLAGの生レポートまたは簡易整形した内容をSlackへ通知する。

```text
JUSLAG成功
LLM要約失敗
  ↓
生レポートをフォールバック通知
  ↓
history.jsonlには失敗情報を保存
```

---

### 6.3 Slack通知失敗

Slack通知に失敗した場合も、データ保存とcommitは実施する。
ただし、Actions上では失敗として検知できるようにする。

---

## 7. 保存方針

取得データはリポジトリ保存でよい。

ただし、以下の方針にする。

### 保存してよいもの

* 公開データ
* 再取得可能な市場データ
* JUSLAGの分析結果
* 日次サマリー
* バックテスト結果
* シグナル履歴

### 保存に注意するもの

* APIキー
* 認証トークン
* 有料データそのもの
* 個人の保有銘柄
* 資産額
* 売買予定
* 外部公開したくない独自戦略ロジック

これらを含む場合、リポジトリはprivate前提にする。
GitHub Pagesで公開する場合は、表示内容を要約・匿名化・限定化する。

---

## 8. 運用上のメリット

この構成のメリットは以下。

* サーバを常時稼働させなくてよい
* 日次処理をGitHub Actionsで自動化できる
* 取得データと判断履歴がGitに残る
* Slackで結果を即確認できる
* GitHub Pagesで過去結果を一覧できる
* 手動実行も可能
* 構成が単純で保守しやすい

---

## 9. 注意点

GitHub Actionsのcronは厳密な時刻実行ではない。
市場開始直前など、分単位の厳密性が必要な用途には向かない。

また、GitHub Pagesは静的ホスティングであり、JUSLAG本体を実行する場所ではない。
実行はGitHub Actions、表示はGitHub Pages、保存はリポジトリという役割分担を明確にする。

---

## 10. 最終構成

最終的な構成は以下とする。

```text
GitHub Actions
  ↓
JUSLAG日次処理
  ↓
取得データをリポジトリ保存
  ↓
日次レポート生成
  ↓
agy / LLMで要約
  ↓
history.jsonlへ追記
  ↓
Slack通知
  ↓
GitHub Pages用HTML生成
  ↓
生成物をcommit / push
```

本構成では、GitHub Actionsを実行基盤、GitHub Repositoryをデータ保存先、GitHub Pagesを閲覧用UI、Slackを通知先として利用する。
