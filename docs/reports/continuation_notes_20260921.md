# JUSLAG 詳細引き継ぎメモ（2026-09-21）

## 最初に読む結論

- 作業場所は`/home/quieter/projects/JUSLAG`。ブランチは`main`、このメモ作成直前のコードHEADは`b47f68f`で`origin/main`へpush済み、作業ツリーはcleanだった。
- 戦略の実売買判断は**No-Go**。これは実装未完了という意味ではなく、現行証拠では資金投入を正当化できないという確定判断。自動発注は実装・許可していない。
- A1～A3の過去データ調査は完了。今後は固定済みの前向きゲートを変更せず、A2を60 JPX営業日、A3を120 JPX営業日観測する。
- 日次バッチ、GitHub Pages、Slack、Turso二重保存、照合、価格データ移行は稼働経路がある。Gitの`data/`とローカルSQLiteを正本として維持し、TursoはCloud保存・閲覧候補である。
- GitHub Actionsの時刻精度が不足したため、A2の寄り後バー取得はSSHホストのsystemd user timerを主系、Actionsを補助系にした。
- 2026-09-21にPR/main用CIを追加。サービスへ渡した`PriceCache`が実際のデータ取得に使われない不具合も修正した。外部通信・既存HOMEなしで全300テストが通る。
- Codex remote-controlはstandalone版`0.155.1`を導入し、重複登録を解除して`connected`まで復旧した。秘密のペアリングコードは本書へ記録しない。

## 戦略の確定判断と前向きゲート

採否の正本資料は[`a1_a3_final_decision_20260919.md`](a1_a3_final_decision_20260919.md)。要点は以下。

1. 現行メタ版はJP寄りgapを観測してから同じ寄り値で約定する必要があり、情報時系列として成立しない。
2. 保存済み52日次レポートのうち寄り前生成30件はすべて当日gapを含み、うち20件が`tradeable=true`だった。同時保存rawには対象日JP価格がなく、旧判断を執行証拠として再現できない。
3. 固定5日ロングは資金制約・コスト・税を入れても探索期間ではプラスだが、条件選択後と同じ期間の結果であり、独立した採用証拠ではない。
4. 現行メタ版も固定5日ロング候補も研究専用。途中成績による条件変更は禁止。

固定条件は`config/a_evaluation_gate.yaml`、判定は`scripts/reports/check_a_evaluation_gate.py`。

- A2代理観測: 2026-09-24開始、期限内観測60 JPX営業日、銘柄日カバレッジ90%以上、バー開始から20分以内。
- A2のGoには代理バーだけでなく、SBI由来の注文・受付・約定時刻、方向、数量、価格、売建可否・料金等が必要。
- A3未使用期間: 2026-09-24～2027-03-23、120 JPX営業日。
- A3固定仕様: PCA SUBロングのみ、5営業日保有、元本100万円、非重複、片道5bps、年次税支払い。
- A3解除条件: 税後最終資金が元本超過、税後決済時最大DDが-25%以上、同元本17業種平均との差が0bps超、期間終了までパラメータ変更なし。
- 解除には新しい日付付き採否資料と明示承認が必要。ゲート通過だけで自動発注しない。

## A2寄り後バー収集

### 主系: ローカルsystemd timer

- unit: `config/systemd/juslag-opening-bars.service`
- timer: `config/systemd/juslag-opening-bars.timer`
- installer: `scripts/ops/install_opening_bars_timer.sh`
- 平日09:16/09:40 JST、`AccuracySec=10s`、`Persistent=false`。
- `Persistent=false`は、停止中に逃した観測を後から取得して「期限内観測」に見せないため。
- `loginctl enable-linger quieter`を実施済み。SSH切断後もuser timerが動く構成。
- 手動service実行は17銘柄・575本を保存して終了コード0。2026-09-21は休場日のため当日opening snapshotは0件だった。
- 次に必要なのは最初のJP営業日に、実観測時刻、17銘柄のカバレッジ、20分以内条件を確認すること。

確認コマンド:

```bash
systemctl --user status juslag-opening-bars.timer
systemctl --user list-timers juslag-opening-bars.timer
journalctl --user -u juslag-opening-bars.service --no-pager -n 200
PYTHONPATH=src .venv/bin/python scripts/reports/check_a_evaluation_gate.py
```

### 補助系: GitHub Actions

- workflow: `.github/workflows/opening-bars.yml`
- schedule: 平日09:16/09:40 JST相当。
- 2026-09-21はworkflowが`active`でもschedule run自体が作成されなかった。GitHub scheduleを時刻証拠の主系にしない。
- 土曜の手動run `35421759823`は成功している。

## 日次処理・Turso・データ配置

### 正本と複製

- Git正本: `data/reports/*.json`、`data/history.jsonl`、関連する`data/`生成物。
- ローカル価格正本/キャッシュ: `~/.juslag/prices.db`。
- GitHub Actions価格キャッシュ: `~/.juslag/prices.db`を`actions/cache`へ保存。
- ローカル分足: `data/intraday/prices.sqlite`。Git管理外。
- 前向きopening bars: `data/opening_bars/`。期限内観測の証拠としてGitへ保存。
- Turso Cloud: `juslagdb`、東京リージョン。Git/SQLiteのCloud複製であり唯一の正本ではない。
- `.env.turso`はGit管理外・権限600。値、token、Pagesパスワードをログ・資料・commitへ書かない。

### Turso実装状況

- 既存52日分のレポート、価格224,924行、401ファイルをCloudへ移行し、別接続で全件照合済み。
- 日次workflowの`turso` jobが確定日次ファイルをpublishし、同runの価格キャッシュとGitデータを同期する。
- `.github/workflows/turso-reconcile.yml`が平日09:30 JSTにGit正本とCloudを照合する。欠落・差分は設定に従い再送する。
- `pyturso==0.7.2`の公式`pull()`/`push()`を利用。ブラウザへDB tokenは渡さない。
- Turso使用量は大量同期後にRows Read/WrittenとEmbedded Syncsが増えた。公開読み取りをCloudへの高頻度直読みにはせず、クエリ・同期頻度・キャッシュを`.agents/skills/juslag-turso-usage/SKILL.md`に従って監査する。
- 詳細資料: [`turso_full_migration_20260918.md`](turso_full_migration_20260918.md)、[`turso_actions_verification_20260918.md`](turso_actions_verification_20260918.md)、[`../turso_credentials.md`](../turso_credentials.md)。

安全な再開確認:

```bash
gh run list --repo yaziuma/JUSLAG --workflow daily-juslag.yml --limit 10
gh run list --repo yaziuma/JUSLAG --workflow turso-reconcile.yml --limit 10
python3 scripts/ops/check_turso_reconcile_streak.py
```

書込修復では`JUSLAG_WRITE_TURSO=1`を明示し、先にGit正本、対象日、修復件数を確認する。資格情報の読み込み方法は`docs/turso_credentials.md`を使い、`set -x`を有効にしない。

## GitHub Pagesと認証

- GitHub Pagesは日次workflowの`site` jobから生成する。`ENABLE_SITE_DEPLOY=true`時だけ実行。
- `scripts/ops/render_pages.py`が静的サイトを生成し、StatiCryptで各HTMLを保護する。
- パスワードはActions Secret `SITE_PASSWORD`。資料やリポジトリへ平文保存しない。
- saltはJST日付から決定的に生成し、`--remember 1`で同日中の認証をブラウザに保持する。画面遷移ごとの再入力を避け、日付変更後は再認証する設計。
- これは簡易な静的閲覧保護であり、ブラウザへTurso tokenを配る根拠にはしない。
- 運用資料: [`../github_pages_operations.md`](../github_pages_operations.md)。

## 2026-09-21のコード修正とCI

### 修正した不具合

`run_backtest_service(params, cache)`、`run_daily_signal_service(cfg, cache)`、`run_fetch_all(..., cache)`はキャッシュ引数を受け取っていたが、`fetch_data()`がmodule-global `_cache`を固定使用していた。このため、呼び出し側が指定した一時DBや明示的キャッシュが実取得に使われなかった。

修正:

- `src/juslag/data_loader.py`: `fetch_data(..., cache: PriceCache | None = None)`を追加し、明示cacheをUS/JP両市場へ渡す。
- `src/juslag/services/backtest.py`: cacheを`fetch_data()`へ伝播。
- `src/juslag/services/daily_signal.py`: 同上。
- `src/juslag/services/fetch_all.py`: 同上。
- `tests/test_data_loader.py`: US/JP両方が明示cacheを使う回帰テスト。
- `tests/test_strategy_rule_backtest.py`: Yahoo通信と既存HOME DBを使わず、決定的合成パネルで統合テスト。

### CI

- `.github/workflows/ci.yml`を追加。
- `pull_request`と`main`へのpushで実行。
- `ubuntu-24.04`、15分timeout、`contents: read`のみ。
- Actionsは40文字commit SHAで固定。
- `uv sync --frozen --extra dev`、変更PythonファイルへのRuff、HOMEを空の一時ディレクトリにした全pytestを実行。
- mainのrun `35561976678`は成功（1分45秒）。Dependabot PR #4のrun `35562084825`も成功。
- ローカル検証: `HOME=/tmp/juslag-ci PYTHONPATH=src .venv/bin/pytest -q`で`300 passed, 42 warnings`。
- 全リポジトリRuffには今回と無関係の既存17件がある。CIは変更Pythonファイルをlintし、既存負債で全PRを停止しない。

commitとActions hardening:

- `b47f68f ci: add hermetic pull request checks`
- `61ac366 Add precise local opening-bar timer`
- `7b0ea6a Test GitHub Actions security policy`
- `b70a26d Configure Dependabot for GitHub Actions`
- `7376dbf Pin third-party Actions by commit SHA`
- `c5b1165 Pin Actions runners to Ubuntu 24.04`

## Dependabot PR

2026-09-21時点でGitHub Actionsのメジャー更新PR #1～#5が開いている。

- #1 `actions/deploy-pages` 4.0.5 -> 5.0.1
- #2 `actions/checkout` 5.1.0 -> 7.0.1
- #3 `actions/cache/restore` 4.3.0 -> 6.1.0
- #4 `actions/upload-pages-artifact` 3.0.1 -> 5.0.0
- #5 `actions/cache` 4.3.0 -> 6.1.0

全PRへbase branch update APIを実行したが、CIが確認できたのは#4のみ。#4は成功。メジャー更新なので、残りもチェックを発火・確認し、各Actionのランタイム要件と破壊的変更を確認してから個別にマージする。一括マージしない。

## Codex remote-control

### 現在状態

- npm版Codexだけでは`remote-control`デーモンを起動できなかったため、OpenAI公式installerからstandalone版`0.155.1`を導入。
- 実体: `/home/quieter/.codex/packages/standalone/current/bin/codex`
- CLI: `/home/quieter/.local/bin/codex`
- `~/.bashrc`へ`~/.local/bin`のPATHが追加された。新しいshellではstandalone版が先に解決される。
- 初回登録後、アプリではホスト情報が見えるがチャット接続不能だった。デバッグログでremote-control専用WebSocketがHTTP 409 `Remote app server already online`を返すことを確認。
- `state_5.sqlite`を`/tmp/juslag-codex-state-before-remote-reset.sqlite`へbackupし、`remote_control_enrollments`の重複1行だけを削除して再登録。
- 再起動結果は`status=connected`、新しいenvironment IDが払い出された。ペアリングコードは短期秘密情報のため記録しない。

確認・復旧:

```bash
/home/quieter/.local/bin/codex doctor --summary
/home/quieter/.local/bin/codex remote-control start --json
/home/quieter/.local/bin/codex remote-control pair --json
tail -n 200 ~/.codex/app-server-daemon/app-server.stderr.log
```

`start`が`connected`なら基盤接続は正常。`409 Remote app server already online`なら同一登録の古い接続が残っている。DB行を直接変更する前に必ずdaemon停止とSQLite backupを行う。ペアリング済み旧環境はアプリ側から削除し、新コードで登録する。

注意: この会話自体はstandalone daemon導入前に開始した既存セッションである。remote-controlから新規チャットは作れても、この既存会話へライブ接続できない可能性がある。その場合は新規チャットで本書を最初に読ませ、`git status`とHEADを再確認して続行する。

## 次に行う作業

優先順:

1. 最初のJP営業日後にローカルtimerの09:16/09:40実行、観測遅延、銘柄カバレッジ、A2ゲート進捗を確認する。翌日まで待つ間は以下の2～5を進める。
2. Dependabot PR #1/#2/#3/#5でCIを発火させ、公式変更点と互換性を個別確認する。成功してもメジャー更新を自動マージしない。
3. Turso reconcileの連続成功回数、最新日次publish、Git正本との不一致0件を確認する。Cloud読取・同期量を不必要に増やさない。
4. B2 Viewerは未完成。静的Pagesへtokenを埋めず、認証済み静的スナップショットを当面維持する。将来のCloud viewerは認証付きAPI等を別設計する。
5. 全体Ruff既存17件を小さな独立commitで解消し、その後CIを全Python lintへ強化する。ただし戦略ロジックの変数名変更は回帰テストを伴わせる。
6. A2のSBI実注文・約定証拠は未取得。実資金試験を勝手に開始しない。実施する場合は極小・別試験・明示承認・固定保存項目が必要。

## 新規チャットでの開始手順

```bash
cd /home/quieter/projects/JUSLAG
git status --short --branch
git log -5 --oneline --decorate
git fetch origin
gh run list --repo yaziuma/JUSLAG --limit 15
systemctl --user status juslag-opening-bars.timer --no-pager
PYTHONPATH=src .venv/bin/python scripts/reports/check_a_evaluation_gate.py
```

期待状態は`main...origin/main`で未追跡・変更なし。差分があればユーザー作業とみなし、理由を確認せずに削除・revertしない。ネットワークや外部サービスの状態は日付依存なので、GitHub/Turso/systemdを実測してから判断する。
