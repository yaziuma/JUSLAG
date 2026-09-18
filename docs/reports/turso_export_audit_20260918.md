# Tursoエクスポート検査（2026-09-18）

本番`juslagdb`を公式CLIの`turso db export`で`/tmp`へ**読み取り専用で取得**し、`scripts/ops/verify_turso_export.py`でSQLiteの`PRAGMA integrity_check`とGit正本に対する内容ハッシュ照合を実施した。結果は`Export: 3 snapshot row(s), 0 date(s) differ from Git`。この3行は同日の再実行を含む行数であり、3営業日分の実績ではない。エクスポートファイルとWALはリポジトリ外に置き、権限0600で保存した。

再検査は次の手順。出力ファイル名は毎回新しくし、検査後も機密データとして扱う。

```bash
umask 077
turso db export juslagdb --output-file /tmp/juslag-export-YYYYMMDD.db
uv run --frozen --extra turso python scripts/ops/verify_turso_export.py --db /tmp/juslag-export-YYYYMMDD.db
```

これは**取得したファイルの読取可能性と現在のGit内容との一致**のみを確認する。別のCloud DBへの`--from-file`インポート、切替、PITR、障害時の所要時間は未検証。復元試験では別名DBを作成し、元DBの削除・上書きを行わず、接続先切替前に同じハッシュ検査を行う。Cloud作成と新しい資格情報の発行は別途承認を得てから実施する。公式CLIの[エクスポート](https://docs.turso.tech/cli/db/export)と[ダンプ/再読込](https://docs.turso.tech/cli/db/shell)を参照。
