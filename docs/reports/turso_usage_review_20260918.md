# Turso利用量レビュー（2026-09-18）

## 実測と上限

同日、認証済みの公式CLI `turso plan show` と `turso db inspect juslagdb` で確認した。表示値は集計遅延・丸めを含み得るため、単一ジョブの請求量とはみなさない。

| 項目 | 組織使用量 | 現契約の上限 | `juslagdb`表示値 |
| --- | ---: | ---: | ---: |
| Storage | 98 kB | 5.0 GB | 98 kB |
| Rows read | <0.1M | 500M | 243 |
| Rows written | <0.1M | 10M | 41 |
| Embedded syncs | 1.2 MB | 3.0 GB | 1.2 MB |
| Databases | 2 | 100 | - |
| Locations | 3 | 3 | - |

契約はStarter、overages disabled。次回リセット表示は2026-10-01 09:00 JST。Locationsは上限に達しているが、本件で追加する計画はない。数値は契約・集計方法の変更を受け得るので、閾値判定前に必ず再取得する。超過課金が無効でも上限到達時の機能制限は避けたい。

## 負荷経路と予算

- Pages閲覧はGit上の生成済みファイルを使い、Tursoへのブラウザ接続は0回。公開トラフィックがTursoクエリを誘発する経路はない。
- 日次publishはActionsの一時ローカルDBでCloudから1回pullし、スキーマ確認後のpushと新規行追加後のpushが最大2回、別クライアントで読み戻しのpullが1回。照合は平日1回、監査時は1回pull、修復時は追加pushと読み戻しpull。対象日ごとにはpullしない。手動実行・失敗時の再試行はこの回数に上乗せされる。
- 同期量1.2 MBは運用開始日の複数回のPoC・手動監査を含み、定常1日分の実測ではない。初回pullの量はDBの増大で伸びる。3 GB枠に対する将来の安全性はまだ実証できていない。
- 当面は組織のEmbedded syncsが上限の50%を超えたら原因調査、70%を超えたら新規の手動Syncを抑制し、定期照合の停止・直接書込方式または保持範囲の見直しを判断する。Rows read/writtenとStorageも同じ比率を確認する。90%到達時は`JUSLAG_WRITE_TURSO=false`でTurso書込・照合を停止し、Git/Pages/Slackの経路を維持する。閾値は運用上の自主基準で、Turso提供のアラートではない。
- 通知先は既存のSlack webhook。現在のActionsは照合失敗のみを通知し、使用量閾値の自動通知は**未実装**。公式CLIの対話認証をそのままCIへ移すことはしない。自動化には別の管理API資格情報が要るため、最小権限と更新・失効手順を決めてから導入する。

## 確認手順と残件

毎週と、大量の手動再送・DB構造変更の前後に、認証済みSSH端末で `turso plan show`、`turso db inspect juslagdb` を確認する。増分測定では集計遅延を考慮して翌日も再確認し、実行前後の累計差を記録する。閾値超過ならTursoジョブ停止後、既存のGit正本から復旧できることを照合する。

公式[CLIの契約表示](https://docs.turso.tech/cli)、[組織の契約API](https://docs.turso.tech/api-reference/organizations/subscription)、[プランAPI](https://docs.turso.tech/api-reference/organizations/plans)を確認した。今回調べた公式資料には利用量閾値の自動通知設定は見当たらず、標準機能がないと断定はしない。次の判断は、管理APIトークンを追加してActionsで自動監視するか、当面の小規模運用では手動週次確認を続けるか。どちらの場合も定常10回の照合・使用量推移の記録が必要。
