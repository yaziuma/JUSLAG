# Turso全データ移行結果（2026-09-18）

## 移行済みデータ

- 日次レポート: `2026-07-09`〜`2026-09-18`の52日・54 run。Git正本と全日付の最新runが一致。
- 価格: 28銘柄のraw/adjusted各112,462行、計224,924行。日付範囲は`2010-01-04`〜`2026-09-18`。最新[Actionsキャッシュ](https://github.com/yaziuma/JUSLAG/actions/runs/35310809472)から投入し、別接続で全行を照合した。[移行Actions #35318039825](https://github.com/yaziuma/JUSLAG/actions/runs/35318039825)は`PASS: artifacts=366 changed=0 prices=224924 changed=0`。失敗した初回実行で全行が反映され、再実行では変更0だった。
- `data/`ファイル: Git管理の366ファイルに加え、ローカルのGit管理外`data/external/`等35ファイルを投入し、計401ファイルの内容を別接続から検証。Turso表`juslag_artifacts`は相対パス・SHA-256・BLOBを持つ。価格表`juslag_prices`は`(ticker,date,price_mode)`を主キーとする。Git管理外の新規・変更ファイルは、ローカルから`uv run --frozen --extra turso python scripts/ops/turso_data.py`を再実行して更新する。

元の価格SQLiteは変更せず、Actionsでその回に使ったDBを**同じrun IDのActions Cache**からTursoジョブが復元する。公開リポジトリなので価格DBをworkflow artifactにはアップロードしない。今後の日次ジョブは研究レポート・価格・Git管理ファイルをCloudへ差分更新し、別接続から読み戻す。ブラウザにDB資格情報は渡さず、旧Git/Pages経路も維持する。

## 整合性と索引

Turso Syncから戻るREAL値は元SQLiteと最下位桁が異なる場合があった（例: `11117.936298688901`と`11117.9362986889`）。価格の比較は`rel_tol=1e-12, abs_tol=1e-8`とし、これを超える差は失敗する。これにより丸め差だけの再書込を防ぐ。レポートとファイルはハッシュ/バイト一致のまま。

実DBで`EXPLAIN QUERY PLAN`を比較した。追加前の銘柄・モード・日付範囲検索は`juslag_prices_mode_date (price_mode,date)`を使い、銘柄を索引内で絞れなかった。追加後は`juslag_prices_ticker_mode_date (ticker,price_mode,date)`を使用し、3条件すべてを索引に適用する。全件移行・全件照合の表走査は意図した処理であり、日次の通常画面クエリには使用しない。

## 使用量と接続方式

ユーザーが同日管理画面で確認した途中値はRows Read 2,090、Rows Written 675,783、Storage 28.85 MB、Embedded Syncs 36.01 MB。その後の公式`Turso plan show`はStorage 38 MB/5 GB、Rows Read 0.5M/500M、Rows Written 1.1M/10M、Embedded Syncs 287 MB/3 GB、超過課金無効。複数回の全件試験を含み、定常日次の増分ではない。集計遅延があるため翌日も再確認する。

一時ローカルTurso DBを毎回フル`pull()`する方式では、価格表の増大に伴い3 GBの同期枠を圧迫する。このため日次publisher・照合・価格差分更新は公式`libsql==0.1.11`のリモートSQLへ変更した。元価格データのローカルSQLiteは継続し、Cloudへの更新だけ直接SQLを使う。直接接続の22万行取得は約6.24秒、既存1行の内容不変更新・`executemany`・別接続読戻しも成功。旧`pyturso`はローカルSync PoC/復旧訓練用に残す。[直接SQLの移行Actions #35320096365](https://github.com/yaziuma/JUSLAG/actions/runs/35320096365)は価格224,924行・Git管理366ファイルが一致し、[照合Actions #35320400751](https://github.com/yaziuma/JUSLAG/actions/runs/35320400751)は52日分の差分0。これらの後の公式CLI表示はRows Read 1.4M、Embedded Syncs約287 MBで、少なくとも表示上はフル同期量が増えていない。集計遅延を考慮し、次回定期実行後にも確認する。

停止は`JUSLAG_WRITE_TURSO=false`。Tursoを停止しても研究バッチ・Git正本・Pages・Slackは継続する。使用量の自主閾値は[利用量レビュー](turso_usage_review_20260918.md)。

## 日次経路の実測（2026-09-18）

[手動日次run #35321613413](https://github.com/yaziuma/JUSLAG/actions/runs/35321613413)で研究、同一run IDの価格キャッシュ復元、レポートCloud公開、Pages公開は成功した。価格同期だけは大量の差分が発生し、旧`executemany`経路では45分のジョブ上限で中断した。これは全件一致を確認できた状態ではなく、部分書込み状態だった。

価格差分を1,000行までの複数VALUES文でまとめて送る方式へ変更後、同じ価格キャッシュを使った[移行run #35325950045](https://github.com/yaziuma/JUSLAG/actions/runs/35325950045)は2分で完了し、別接続で`PASS: artifacts=366 changed=0 prices=224924 changed=59865`を確認した。Cloud直接照会でも価格224,924行・28銘柄（`2010-01-04`〜`2026-09-18`）、ファイル401件、レポート55 run/52日、最新run `actions:35321613413:1`。`turso_reconcile.py --since 2026-07-09`は修復必要日0。管理画面のEmbedded Syncsはユーザー共有値で286.82 MBのまま、Rows Writtenは増加しており、直接SQLで差分が反映されたことと整合する。

修正版の[日次run #35326344970](https://github.com/yaziuma/JUSLAG/actions/runs/35326344970)では研究・Turso・Pagesの全ジョブが成功し、同一runの価格キャッシュから価格224,924行を全件読戻しした。ただしこのrunでも72,512行の差分が発生した。同じキャッシュを[再照合 #35327335959](https://github.com/yaziuma/JUSLAG/actions/runs/35327335959)すると変更0なので、Cloud比較・書込みは冪等である。

Actions Cacheの2世代をCloudに接続せず比較したところ、[比較 #35327616790](https://github.com/yaziuma/JUSLAG/actions/runs/35327616790)は73,212行、[比較 #35327624210](https://github.com/yaziuma/JUSLAG/actions/runs/35327624210)は72,085行が変わり、いずれも全件がadjusted系列の過去年分だった。原因は要求開始日`2010-01-01`が初回取引日`2010-01-04`より前であるため、キャッシュが不足と誤判定され、毎回全履歴をyfinanceから再取得していたこと。非取引日の短い先頭ギャップを別取得して確認し、通常の末尾取得を直近7日に限定した。修正後の[dry-run #35328082152](https://github.com/yaziuma/JUSLAG/actions/runs/35328082152)で生成した価格キャッシュは、直前のキャッシュとの[比較 #35328300051](https://github.com/yaziuma/JUSLAG/actions/runs/35328300051)で224,924行すべて一致し、変更0。Cloud側の不要な再書込みは同日再実行では発生しない見込み。翌取引日の新規価格分は次回runで観測する。
