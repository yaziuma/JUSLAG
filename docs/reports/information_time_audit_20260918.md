# 情報時刻の一次監査（2026-09-18）

## 判定

**現行メタ戦略は実売買No-Goを維持する。** シグナル日と次の日本営業日の対応はコード上で確認できたが、メタ判定・銘柄除外に執行日の寄りgapを使いながら、損益は同じ寄り値から計算する。日次OHLCでは、そのgapを知った後に同じ寄り値で約定できることを証明できない。これはコスト仮定を調整するだけでは解消しない。

## コード上の情報時系列

| 段階 | 現行経路 | 情報の利用可能時点 / 残る確認 |
| --- | --- | --- |
| JP終値 | `compute_returns()`でJP前日比を作る | JP取引終了後。データ配信・修正履歴は未記録 |
| US終値 | 同関数でUS前日比を作る | 同一カレンダー日付のJP終値より後。US終値の実際の取得時刻は未記録 |
| シグナル | `build_joint_cc()`のUS/JP共通日を学習窓とし、`generate_signals()`は当日US前日比を利用 | US終値確定後。最新US-only日だけ別経路で追加される |
| 執行日 | シグナル日より後の最初のJP行へ`jp_oc`とgapを対応付ける | `portfolio._next_jp_session_values()`は日付で対応。時刻・実約定は扱わない |
| メタ判定 | `build_portfolio_with_strategy_rule()`が次JP日のgapを`StrategyContext`へ渡す | 寄り値の観測後でないと確定しない |
| 損益 | 同じ次JP日の`close/open - 1`を使用 | 寄り値約定を前提とするため、上段の判定時点と両立未証明 |

日次経路も`run_daily_signal_service()`で執行対象日のgapを選び、ルール判定と銘柄除外に使う。対象日の寄り値がまだない場合、過去日のgapでは代用せず欠損となる。Actionsの定時実行はUTC前日23:00、JST 08:00を意図する。この時刻では通常、当日JP寄りgapは未確定であり、同ルールによる最終的な発注判断は作れない。手動再実行では実際の実行時刻と対象日を分けて記録する必要がある。

## A1で未検証の項目

1. US終値・JP終値の配信時刻、取得完了時刻、再取得による過去値改訂。日付だけの価格キャッシュでは時点再現ができない。
2. US-only/JP-only/両市場休場日に、各シグナルが判断締切時点で取得済みの行だけを使うこと。最新日と履歴でUS-only処理が異なるため、日別の情報集合テストが必要。
3. 寄りgapを観測できる最初の時刻、注文送信・受付・約定時刻、実際の売建可能数量と価格。これはA2の板・ティックまたは実約定記録が必要。
4. `regime_df`とpriorの各日について、学習対象の最終日がその判断時点以前であることを自動検査する。

## 日付順序の自動検査（一次）

`scripts/reports/audit_information_time.py`をローカルraw価格キャッシュに対して実行した。既定の評価期間は2022-01-01以上、2026-09-19未満、pretrain終了日は2021-12-31、学習窓は60共通日。1179のUS市場日付を列挙し、うち72日はUS-only市場日付だった。日付順序の違反は0件。CSVは`/tmp/juslag_information_time_audit.csv`へ出力した。再現: `PYTHONPATH=src .venv/bin/python scripts/reports/audit_information_time.py`。

この検査は各市場で少なくとも1銘柄のraw終値がある日を用いる**暦レベルの一次監査**であり、厳密な学習パネル・全銘柄の利用可能性・実際のシグナル生成日を再現しない。US-only日は履歴シグナルではなく、最新日経路の候補日として記録した。`date_order=ok`でも価格配信時刻は未検証、gap観測後に同値寄り約定できるという仮定も未検証である。

## 次の実装単位

日別監査レコードに`signal_date`、`last_us_input_date`、`last_jp_input_date`、`decision_deadline_jst`、`execution_jp_date`、`gap_observable_at`、`assumed_fill_at`、`audit_result`を持たせる。まず暦と入力行の監査を自動化し、タイムスタンプを持たない価格は「利用可能時刻未検証」として扱う。執行判定は寄り前版と寄り後版を別仕様にし、後者は同値寄り約定を禁止する。

参照: `src/juslag/data_loader.py`、`src/juslag/signal.py`、`src/juslag/portfolio.py`、`src/juslag/services/daily_signal.py`、`.github/workflows/daily-juslag.yml`。
