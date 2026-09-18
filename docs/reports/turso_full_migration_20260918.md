# Turso全データ移行結果（2026-09-18）

## 移行済みデータ

- 日次レポート: `2026-07-09`〜`2026-09-18`の52日・54 run。Git正本と全日付の最新runが一致。
- 価格: 28銘柄のraw/adjusted各112,462行、計224,924行。日付範囲は`2010-01-04`〜`2026-09-18`。最新[Actionsキャッシュ](https://github.com/yaziuma/JUSLAG/actions/runs/35310809472)から投入し、別接続で全行を照合した。[移行Actions #35318039825](https://github.com/yaziuma/JUSLAG/actions/runs/35318039825)は`PASS: artifacts=366 changed=0 prices=224924 changed=0`。失敗した初回実行で全行が反映され、再実行では変更0だった。
- `data/`ファイル: Git管理の366ファイルに加え、ローカルのGit管理外`data/external/`等35ファイルを投入し、計401ファイルの内容を別接続から検証。Turso表`juslag_artifacts`は相対パス・SHA-256・BLOBを持つ。価格表`juslag_prices`は`(ticker,date,price_mode)`を主キーとする。Git管理外の新規・変更ファイルは、ローカルから`uv run --frozen --extra turso python scripts/ops/turso_data.py`を再実行して更新する。

元の価格SQLiteは変更せず、Actionsでその回に使ったDBを**同じrun IDのActions Cache**からTursoジョブが復元する。公開リポジトリなので価格DBをworkflow artifactにはアップロードしない。今後の日次ジョブは研究レポート・価格・Git管理ファイルをCloudへ差分更新し、別接続から読み戻す。ブラウザにDB資格情報は渡さず、旧Git/Pages経路も維持する。日次の新経路そのものは次回定期実行で確認する。

## 整合性と索引

Turso Syncから戻るREAL値は元SQLiteと最下位桁が異なる場合があった（例: `11117.936298688901`と`11117.9362986889`）。価格の比較は`rel_tol=1e-12, abs_tol=1e-8`とし、これを超える差は失敗する。これにより丸め差だけの再書込を防ぐ。レポートとファイルはハッシュ/バイト一致のまま。

実DBで`EXPLAIN QUERY PLAN`を比較した。追加前の銘柄・モード・日付範囲検索は`juslag_prices_mode_date (price_mode,date)`を使い、銘柄を索引内で絞れなかった。追加後は`juslag_prices_ticker_mode_date (ticker,price_mode,date)`を使用し、3条件すべてを索引に適用する。全件移行・全件照合の表走査は意図した処理であり、日次の通常画面クエリには使用しない。

## 使用量と接続方式

ユーザーが同日管理画面で確認した途中値はRows Read 2,090、Rows Written 675,783、Storage 28.85 MB、Embedded Syncs 36.01 MB。その後の公式`Turso plan show`はStorage 38 MB/5 GB、Rows Read 0.5M/500M、Rows Written 1.1M/10M、Embedded Syncs 287 MB/3 GB、超過課金無効。複数回の全件試験を含み、定常日次の増分ではない。集計遅延があるため翌日も再確認する。

一時ローカルTurso DBを毎回フル`pull()`する方式では、価格表の増大に伴い3 GBの同期枠を圧迫する。このため日次publisher・照合・価格差分更新は公式`libsql==0.1.11`のリモートSQLへ変更した。元価格データのローカルSQLiteは継続し、Cloudへの更新だけ直接SQLを使う。直接接続の22万行取得は約6.24秒、既存1行の内容不変更新・`executemany`・別接続読戻しも成功。旧`pyturso`はローカルSync PoC/復旧訓練用に残す。[直接SQLの移行Actions #35320096365](https://github.com/yaziuma/JUSLAG/actions/runs/35320096365)は価格224,924行・Git管理366ファイルが一致し、[照合Actions #35320400751](https://github.com/yaziuma/JUSLAG/actions/runs/35320400751)は52日分の差分0。これらの後の公式CLI表示はRows Read 1.4M、Embedded Syncs約287 MBで、少なくとも表示上はフル同期量が増えていない。集計遅延を考慮し、次回定期実行後にも確認する。

停止は`JUSLAG_WRITE_TURSO=false`。Tursoを停止しても研究バッチ・Git正本・Pages・Slackは継続する。使用量の自主閾値は[利用量レビュー](turso_usage_review_20260918.md)。
