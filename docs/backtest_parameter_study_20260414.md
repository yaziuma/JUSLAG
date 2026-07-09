# 日次シグナル更新ロジック改善 実装報告

実施日: 2026-04-14

---

## 1. 修正ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `src/juslag/signal.py` | `DailySignalResult` dataclass 追加、`evaluate_daily_tradeability()` 追加、`get_todays_signal()` の戻り値を `DailySignalResult` に変更 |
| `src/juslag/config.py` | `StrategyConfig` に `min_signal_spread: float = 0.0` 追加 |
| `webui/main.py` | `evaluate_daily_tradeability` インポート追加、`/api/daily-signal` のレスポンスに新規フィールド追加 |
| `webui/templates/index.html` | Alpine.js state 追加、`loadDailySignal()` / `restore()` 更新、UI に執行可否・日付表示追加 |
| `tests/test_signal.py` | 新規作成（5ケース） |
| `tests/test_webui_contract.py` | `test_daily_signal_response_contract_includes_tradeability_keys` 追加 |

---

## 2. 追加したレスポンス項目一覧 (`GET /api/daily-signal`)

| フィールド名 | 型 | 説明 |
|---|---|---|
| `signal_reference_us_date` | `str \| null` | シグナル計算に使用した US 市場基準日 |
| `execution_target_jp_date` | `str \| null` | 執行対象となる JP 市場の翌営業日（データ内に存在しない場合 null） |
| `trade_signal_strength` | `float` | LONG シグナル平均 − SHORT シグナル平均 |
| `tradeable` | `bool` | 今日の執行可否（総合判定） |
| `trade_block_reason` | `str \| null` | 見送り理由コード（tradeable=true の場合 null） |

---

## 3. `trade_signal_strength` の定義

```
trade_signal_strength = mean(LONG銘柄のシグナル値) - mean(SHORT銘柄のシグナル値)
```

- LONG/SHORT が一方でも空の場合は `0.0`
- 高いほど LONG/SHORT の分離が明確で、コスト耐性が高い

---

## 4. `tradeable` 判定条件（優先順位順）

1. `freshness_ok == False` → **freshness_not_ok**
2. `latest_dates_aligned == False` → **cache_dates_not_aligned**
3. `usable_us_tickers < 1` または `usable_jp_tickers < 1` → **too_few_usable_tickers**
4. `execution_target_jp_date is None` → **no_execution_target_date**
5. LONG/SHORT のどちらかが空 → **too_few_usable_tickers**
6. `trade_signal_strength < min_signal_spread` → **signal_spread_too_small**
7. 上記いずれにも引っかからない → `tradeable = True`

---

## 5. `trade_block_reason` 一覧

| コード | トリガー条件 |
|---|---|
| `freshness_not_ok` | データ新鮮度チェック失敗 |
| `cache_dates_not_aligned` | US/JP の最新日付が一致していない |
| `too_few_usable_tickers` | 有効銘柄数が不足、または LONG/SHORT が生成されない |
| `no_execution_target_date` | JP の翌営業日がデータに存在しない（live 運用時の通常状態） |
| `signal_spread_too_small` | LONG-SHORT スプレッドが `min_signal_spread` を下回る |

---

## 6. UI での表示内容

### 本日のデータ品質カードに追加

- **執行可 / 見送り** バッジ（緑 / 黄）
- 見送り時は理由コードを表示
- シグナル強度を数値表示
- `signal_reference_us_date`（US 基準日）
- `execution_target_jp_date`（JP 執行対象日）

### 行動戦略カードに追加

- ヘッダーに `US: {signal_reference_us_date} 基準` を明示
- `tradeable == false` 時は警告バナー「参考シグナル — 本日は見送り推奨」と理由コードを表示
- JP執行対象日をフローの説明文に併記

---

## 7. テストで確認した内容

```
tests/test_signal.py::test_tradeable_when_spread_sufficient       PASSED
tests/test_signal.py::test_not_tradeable_when_spread_too_small    PASSED
tests/test_signal.py::test_not_tradeable_when_freshness_not_ok    PASSED
tests/test_signal.py::test_not_tradeable_when_no_execution_target_date  PASSED
tests/test_signal.py::test_not_tradeable_when_cache_dates_not_aligned   PASSED
tests/test_webui_contract.py::test_daily_signal_response_contract_includes_tradeability_keys  PASSED
（既存 7 件も全 PASS）
```

合計 13 件 PASS。

---

## 8. まだ残る限界

| 項目 | 内容 |
|---|---|
| `execution_target_jp_date` | live 運用時（`today` がデータの最終日）は `null` になる。JP の祝日カレンダーを別途持てば推定可能だが、今回は未実装。 |
| `min_signal_spread` | デフォルト `0.0`（常に通過）。運用ログを蓄積してから閾値を調整すること。 |
| 最大/最小ポジション件数制限 | 今回は未実装。`max_long_positions` 等は将来拡張として残す。 |
| `trade_signal_strength` の正規化 | 現状は生値。銘柄ユニバースや期間によってスケールが変わるため、正規化指標が欲しい場合は検討が必要。 |
