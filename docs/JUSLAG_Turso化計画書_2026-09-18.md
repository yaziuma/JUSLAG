**JUSLAG**

**Turso化 計画書**

GitHub Actions + Turso Cloud + Browser Local-first Dashboard

| **対象**     | yaziuma/JUSLAG                                                                          |
|--------------|-----------------------------------------------------------------------------------------|
| **作成日**   | 2026-09-18                                                                              |
| **目的**     | 現行のファイル駆動型日次リサーチ基盤を、段階的にTurso中心へ移行するための設計・実施計画 |
| **推奨方針** | 出力系の二重書きから開始し、閲覧系をTurso化。価格キャッシュは最終段階で評価             |

# 1. エグゼクティブサマリー

**結論:** JUSLAGはTurso化との相性が良い。 ただし、いきなり価格キャッシュを置換するのではなく、日次レポート・戦略履歴・シグナル・レジームをTursoへ二重書きし、閲覧系を先に移行する段階方式を推奨する。

- 現行JUSLAGは、GitHub ActionsでPython分析を実行し、JSON/CSV/JSONLを生成、Gitへcommitし、静的HTMLを生成してGitHub Pagesへ配信する「ファイル駆動型」。

- 価格キャッシュはすでにSQLite（~/.juslag/prices.db）であり、Turso/SQLite系への親和性が高い。

- Turso化により、同日再実行時のGit rebase競合、毎日増える生成物commit、静的HTML再生成への依存を減らせる。

- 閲覧側をReact/TypeScript + Turso WASM + OPFSにすると、過去レポート・シグナル・レジームをローカルSQLで検索でき、オフライン閲覧も可能になる。

- Gitは完全廃止せず、ソース・CI・再現性監査用manifestに役割を縮小するのが望ましい。

- Turso Cloud / Sync / Browser WASMは2025-2026に大きく進化しているため、SDK/APIの変化を前提に薄いRepository層で隔離する。

# 2. 現行JUSLAGの構成

リポジトリ内の現行実装を基準に整理すると、主要なデータフローは以下。

GitHub Actions (daily-juslag.yml)  
├─ Python環境構築  
├─ actions/cache から ~/.juslag/prices.db を復元  
├─ daily_research.py 実行  
│ ├─ データ取得  
│ ├─ データ状態判定  
│ ├─ バックテスト  
│ ├─ 日次シグナル生成  
│ └─ レポート生成  
├─ data/raw/YYYY-MM-DD/\*  
├─ data/processed/YYYY-MM-DD/\*  
├─ data/reports/YYYY-MM-DD.json  
├─ strategy_history.jsonl / history.jsonl  
├─ git commit / pull --rebase / push  
└─ 静的HTML生成 + StatiCrypt + GitHub Pages

## 2.1 現在のデータ保存方式

| データ             | 現在の保存先                 | 用途                               | Turso化候補            |
|--------------------|------------------------------|------------------------------------|------------------------|
| 価格キャッシュ     | ~/.juslag/prices.db (SQLite) | yfinance等からの増分価格キャッシュ | Phase 4で評価          |
| 日次レポート       | data/reports/YYYY-MM-DD.json | 日次判断結果                       | Phase 1で二重書き      |
| 戦略履歴           | JSONL                        | 前回比較・履歴                     | Phase 1で二重書き      |
| シグナル           | processed/.../signals.csv    | 銘柄別シグナル                     | Phase 1で二重書き      |
| レジーム           | processed/.../regime.json    | trend/vol/rotation                 | Phase 1で二重書き      |
| 生データ・監査抽出 | raw/YYYY-MM-DD/\*            | 再現性・監査                       | Git/Artifactを当面維持 |
| 閲覧サイト         | 静的HTML + StatiCrypt        | 結果閲覧                           | Phase 2-3でSPA/PWA化   |

# 3. Turso化の目的・非目的

## 3.1 目的

- 日次結果を「ファイル」ではなくクエリ可能なデータとして蓄積する。

- 同日再実行をUPSERTで安全に扱い、Git rebase競合を減らす。

- 静的HTML生成に依存せず、ブラウザから期間・銘柄・戦略・レジームを動的検索できるようにする。

- 将来のPWA/オフライン閲覧を可能にする。

- GitHub Actionsを計算基盤、Tursoをデータ基盤、Webを閲覧基盤として責務分離する。

- Git履歴による監査性を、hash/manifest中心の軽量方式へ整理する。

## 3.2 非目的

- 初期段階でJUSLAGのPython分析ロジックをブラウザへ移植しない。

- 初期段階でGitHub Actionsを廃止しない。

- 初期段階でPriceCacheを即座にTursoへ置換しない。

- Tursoを唯一の監査証跡として扱わない。再現性に必要なcommit SHA・設定hash・入力hashは別途残す。

# 4. 推奨ターゲットアーキテクチャ

GitHub Repository  
┌────────────────────────────┐  
│ Source / Workflow / Config │  
└─────────────┬──────────────┘  
│  
GitHub Actions  
┌─────────────┴──────────────┐  
│ Fetch / Backtest / Signal │  
│ LLM Summary / Slack │  
└─────────────┬──────────────┘  
│ INSERT / UPSERT  
▼  
┌──────────────┐  
│ Turso Cloud │  
│ prices(\*) │  
│ reports │  
│ signals │  
│ regimes │  
│ summaries │  
│ run_manifest │  
└──────┬───────┘  
│ pull / query  
▼  
┌────────────────────────────┐  
│ Browser / PWA │  
│ React + TypeScript │  
│ Turso WASM + OPFS │  
│ charts / search / compare │  
└────────────────────────────┘  
  
(\*) pricesはPhase 4で移行可否を最終判断

## 4.1 責務分担

| 要素              | 責務                                       | 補足                                    |
|-------------------|--------------------------------------------|-----------------------------------------|
| GitHub Repository | ソース・Workflow・設定・監査manifest       | 大量の日次生成物は徐々に縮退            |
| GitHub Actions    | データ取得・Python計算・LLM要約・Slack通知 | 現行資産を最大限維持                    |
| Turso Cloud       | 運用データの永続化・履歴検索               | 日付キーでUPSERT可能                    |
| Browser/PWA       | 閲覧・検索・比較・チャート                 | 必要ならWASM+OPFSでローカル保持         |
| FastAPI（任意）   | 認証・短命トークン発行・管理API            | 公開/個人利用なら初期は不要な可能性あり |

# 5. 推奨データモデル（初期案）

初期移行では「既存JSONを完全正規化しすぎない」ことを推奨する。検索頻度が高いキーだけ列化し、詳細はJSON文字列として保持すると移行が速い。

## 5.1 daily_reports

日次レポート本体。画面で多用するレジームだけ列として抽出し、詳細はreport_jsonに保持する。

CREATE TABLE daily_reports (  
report_date TEXT PRIMARY KEY,  
generated_at_utc TEXT NOT NULL,  
settings_name TEXT,  
trend_regime TEXT,  
vol_regime TEXT,  
rotation_regime TEXT,  
report_json TEXT NOT NULL,  
run_id TEXT,  
source_commit TEXT  
);

## 5.2 signals

銘柄別の日次シグナル。将来の期間検索・銘柄比較を想定。

CREATE TABLE signals (  
trade_date TEXT NOT NULL,  
ticker TEXT NOT NULL,  
side TEXT,  
signal REAL,  
rank INTEGER,  
payload_json TEXT,  
PRIMARY KEY (trade_date, ticker)  
);  
CREATE INDEX idx_signals_ticker_date  
ON signals(ticker, trade_date);

## 5.3 summaries

LLM要約履歴。現行JSONLの置換候補。

CREATE TABLE summaries (  
report_date TEXT PRIMARY KEY,  
summary TEXT NOT NULL,  
generated_at_utc TEXT NOT NULL,  
model_info TEXT  
);

## 5.4 run_manifest

再現性・監査用。Gitへ大量データを毎日commitしなくても、どのコード・設定・入力で生成した結果か追跡できるようにする。

CREATE TABLE run_manifest (  
run_id TEXT PRIMARY KEY,  
report_date TEXT NOT NULL,  
source_commit TEXT NOT NULL,  
settings_hash TEXT,  
input_hash TEXT,  
output_hash TEXT,  
github_run_url TEXT,  
created_at_utc TEXT NOT NULL  
);

# 6. 段階移行計画

| Phase | 対象           | 実施内容                                                           | 既存動作                          | 完了判定                                 |
|-------|----------------|--------------------------------------------------------------------|-----------------------------------|------------------------------------------|
| 0     | 準備           | Turso環境作成、schema/migration、Repository抽象化、Secrets設定     | 変更なし                          | 接続・migration・CIテスト成功            |
| 1     | 出力系二重書き | reports / summaries / signals / regimes / manifest をTursoへUPSERT | JSON/CSV/JSONL + Git commitを維持 | Git生成物とTurso結果が連続10回一致       |
| 2     | 読み取りPoC    | React/TSでTursoから過去30日を表示。検索/比較を実装                 | 現行Pagesも維持                   | 主要画面がTursoデータで再現できる        |
| 3     | 閲覧系切替     | SPA/PWA化。必要ならWASM+OPFS。StatiCrypt依存を縮小                 | 旧Pagesを一定期間残す             | 新画面の運用安定・認証方針確定           |
| 4     | PriceCache評価 | actions/cache+SQLiteをTurso Sync/Cloudへ置換する価値をベンチマーク | 現行SQLiteを比較対象として保持    | 速度・安定性・費用・再現性が基準を満たす |
| 5     | 整理           | 不要なdata生成物・render_pages・旧認証手順を縮退                   | rollback用タグ/手順保持           | 運用文書更新・不要処理削除               |

## 6.1 Phase 1を最優先にする理由

- 分析計算そのものに触れないため、障害が投資判断ロジックへ波及しにくい。

- 現行ファイル出力とTursoを比較でき、データ差分を機械的に検証できる。

- 同日再実行時のUPSERTや履歴検索など、Tursoの利点を早期に確認できる。

- うまくいかなければTurso書き込みを止めるだけで即時ロールバックできる。

# 7. メリット

| メリット             | 内容                                                                                                |
|----------------------|-----------------------------------------------------------------------------------------------------|
| Git競合の削減        | 同日再実行をINSERT/UPSERTで扱えるため、生成物commit→pull --rebase→pushの競合要因を減らせる。        |
| 履歴検索の自由度     | 期間、ticker、side、regimeなどをSQLで直接絞り込める。静的HTML生成時に画面を固定する必要がない。     |
| UIの動的化           | レジーム推移、LONG/SHORT履歴、銘柄別時系列、期間比較をオンデマンドで描画可能。                      |
| ローカルファースト化 | Browser WASM + OPFS + Syncを採用すれば、取得済みデータをローカルSQLで閲覧し、オフライン利用も可能。 |
| 責務分離             | GitHub=コード/CI、Turso=データ、Web=UIとなり、現在のRepositoryへの役割集中を解消できる。            |
| SQLite資産との親和性 | PriceCacheが既にSQLiteなので、将来のTurso化を検証しやすい。                                         |
| 将来拡張             | PWA、スマホ閲覧、複数ビュー、API連携、AIによる過去結果検索などに展開しやすい。                      |
| リポジトリ肥大化抑制 | 日次CSV/JSONの継続commitを減らせる。Gitは再現性manifest中心にできる。                               |

# 8. デメリット・注意点

| デメリット/リスク        | 影響                                                                                                            | 対策                                                                       |
|--------------------------|-----------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| 外部サービス依存         | Turso Cloud障害・仕様変更・料金変更の影響を受ける。重要な再現性情報をTursoだけに置かない。                      | manifest/バックアップ維持。Turso書込失敗でも日次分析自体は完了できる設計。 |
| SDK/製品の変化が速い     | Turso Database/Sync/Cloudは2025-2026に機能追加が多い。アプリ内にSDK呼び出しを散らさずRepository層へ閉じ込める。 | DBアクセスをadapter/repositoryへ隔離。バージョン固定と契約テスト。         |
| 認証設計が必要           | ブラウザへ固定の強権限tokenを埋め込まない。非公開利用なら短命read-only token発行の仕組みを検討する。            | write tokenはActions Secretのみ。ブラウザはread-onlyか短命token。          |
| ブラウザ制約             | WASM+OPFSはCOOP/COEP等のヘッダー、ブラウザ互換性、ストレージ消去、複数タブ利用などの実装上の注意がある。        | Phase 2でPC/Android/iOS実機PoC。OPFSを唯一の原本にしない。                 |
| 二重書き期間の複雑化     | 移行期間中はファイルとDBの両方を維持するため、一時的にコード量と検証項目が増える。                              | 期間を限定し、比較テストを自動化。                                         |
| 監査思想の変更           | 「Git履歴=データ監査ログ」が弱くなるため、run_manifest、hash、必要なraw artifact保存の新ルールが必要。          | source_commit/settings_hash/input_hash/output_hash/run URLを保存。         |
| 価格キャッシュ移行リスク | PriceCacheは計算の入力基盤。Sync方式やネットワーク障害が日次処理へ影響しないか、十分なベンチマークが必要。      | Phase 4まで触らない。現行SQLiteと処理時間/結果一致を比較。                 |
| SQLスキーマ運用          | これまでファイル形式変更で済んでいた変更が、migration管理を伴うようになる。                                     | migrationスクリプトとschema_versionを導入。                                |

# 9. セキュリティ方針

- GitHub Actionsの書き込み用Turso credentialはGitHub Secretsにのみ保存する。

- ブラウザへ書き込み権限を与えない。JUSLAG Viewerは原則read-onlyとする。

- 固定tokenをソースへ直書きしない。非公開サイトとして運用する場合は、認証後に短命tokenを発行する小さなAPI（FastAPI Serverless等）を検討する。

- OPFSのローカルDBは「キャッシュ/レプリカ」と扱い、消去されてもCloudから再構築可能にする。

- 投資判断の内部情報・APIキー・Slack Webhook・LLM credentialはDB閲覧データと分離する。

# 10. 実装タスク案

| ID   | タスク                                | 成果物                                          | 優先度 |
|------|---------------------------------------|-------------------------------------------------|--------|
| T-01 | Turso dev/prod DB作成・credential管理 | 接続情報/Secrets設定                            | 必須   |
| T-02 | schema.sql / migration導入            | daily_reports, signals, summaries, run_manifest | 必須   |
| T-03 | Python TursoRepository作成            | DBアクセスを1モジュールへ隔離                   | 必須   |
| T-04 | daily_research.py出力の二重書き       | ファイル + Turso                                | 必須   |
| T-05 | 結果整合性検証                        | JSON/CSVとTurso行の比較テスト                   | 必須   |
| T-06 | 同日再実行テスト                      | UPSERT/idempotency確認                          | 必須   |
| T-07 | 障害時フォールバック                  | Turso障害でもファイル出力継続                   | 必須   |
| T-08 | React/TS Viewer PoC                   | 最新/履歴/シグナル/レジーム画面                 | 高     |
| T-09 | Browser WASM + OPFS PoC               | ローカルDB/再読込/オフライン検証                | 中     |
| T-10 | 認証方式決定                          | public/read-only/短命JWTの選択                  | 高     |
| T-11 | run_manifest導入                      | commit/hash/run URL記録                         | 高     |
| T-12 | PriceCacheベンチマーク                | 現行SQLite vs Turso Sync/Cloud                  | 後半   |
| T-13 | 旧Pages縮退                           | render_pages/StatiCrypt/data commit整理         | 最終   |

# 11. 受入基準・Go/No-Go

| 観点         | 受入基準                                                                     |
|--------------|------------------------------------------------------------------------------|
| データ一致   | 同一入力・同一commit・同一設定で、ファイル出力とTurso主要項目が一致する。    |
| 冪等性       | 同一日を複数回実行しても重複せず、意図したUPSERTになる。                     |
| 障害耐性     | Turso書き込み失敗時も日次分析・Slack通知の既存経路が必要に応じて継続できる。 |
| 閲覧性能     | 直近数年分の主要画面が実用的なレスポンスで表示できる。                       |
| 監査性       | 任意の日次結果からsource_commit、設定hash、GitHub Runへ追跡できる。          |
| セキュリティ | ブラウザにwrite credentialやGitHub/Slack/LLM秘密情報を露出しない。           |
| ロールバック | Turso機能フラグをOFFにすると現行ファイル駆動方式へ戻せる。                   |

# 12. ロールバック設計

JUSLAG_WRITE_TURSO=false \# Turso二重書きを停止  
JUSLAG_READ_TURSO=false \# 新Viewer/読取経路を停止  
  
現行経路:  
Python → JSON/CSV/JSONL → Git → Pages  
  
Turso経路はFeature Flagで追加し、移行期間中は現行経路を削除しない。

Phase 1〜2ではTursoは「追加経路」に限定する。問題があればfeature flagをOFFにし、既存のGit/Pages運用へ戻す。Phase 3以降で旧経路を削除する際も、安定運用期間後にタグ/手順書を残してから実施する。

# 13. 推奨判断

**推奨:** Turso化PoCを実施する価値は高い。ただし「全面移行」ではなく、出力系二重書きから始める。

- JUSLAGはread-heavy、日次append型、既存SQLiteあり、静的ダッシュボードあり、Actionsで計算済みというTurso向きの条件が揃っている。

- 最大の初期効果はPriceCache高速化ではなく、「Gitをデータベース代わりに使う部分」の解消と、閲覧UIの動的化。

- PriceCacheは技術的には移行しやすいが、投資判断計算の入力基盤なので最後に評価する。

- 最初のPoC成功条件は「Actions → Turso → ブラウザで過去30日をSQL検索」の一本道を通すこと。

# 14. 参照資料

- JUSLAG repository: [<u>https://github.com/yaziuma/JUSLAG</u>](https://github.com/yaziuma/JUSLAG)

- JUSLAG daily research architecture: [<u>https://github.com/yaziuma/JUSLAG/blob/main/docs/daily_research_batch_architecture.md</u>](https://github.com/yaziuma/JUSLAG/blob/main/docs/daily_research_batch_architecture.md)

- JUSLAG daily_research.py: [<u>https://github.com/yaziuma/JUSLAG/blob/main/scripts/ops/daily_research.py</u>](https://github.com/yaziuma/JUSLAG/blob/main/scripts/ops/daily_research.py)

- JUSLAG cache.py: [<u>https://github.com/yaziuma/JUSLAG/blob/main/src/juslag/cache.py</u>](https://github.com/yaziuma/JUSLAG/blob/main/src/juslag/cache.py)

- JUSLAG GitHub Actions workflow: [<u>https://github.com/yaziuma/JUSLAG/blob/main/.github/workflows/daily-juslag.yml</u>](https://github.com/yaziuma/JUSLAG/blob/main/.github/workflows/daily-juslag.yml)

- JUSLAG GitHub Pages operation: [<u>https://github.com/yaziuma/JUSLAG/blob/main/docs/github_pages_operations.md</u>](https://github.com/yaziuma/JUSLAG/blob/main/docs/github_pages_operations.md)

- Turso in the Browser (WASM/OPFS): [<u>https://turso.tech/blog/introducing-turso-in-the-browser</u>](https://turso.tech/blog/introducing-turso-in-the-browser)

- Turso Sync: [<u>https://turso.tech/blog/introducing-databases-anywhere-with-turso-sync</u>](https://turso.tech/blog/introducing-databases-anywhere-with-turso-sync)

- Turso Sync recommendation / benchmark: [<u>https://turso.tech/blog/sync-benchmark</u>](https://turso.tech/blog/sync-benchmark)

- Turso 2026 SQLite compatibility status: [<u>https://turso.tech/blog/turso-0.6.0</u>](https://turso.tech/blog/turso-0.6.0)

- Turso Cloud concurrent writes preview: [<u>https://turso.tech/blog/concurrent-writes-on-turso-cloud</u>](https://turso.tech/blog/concurrent-writes-on-turso-cloud)

**注記:** Tursoは2025〜2026年に製品・SDKの更新が速いため、実装着手時には使用SDK・Cloud機能・認証方式の最新版を再確認すること。
