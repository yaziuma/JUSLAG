# Reproduction Plan

1. `reproduction` モードの期間でUS/JPデータを取得
2. pretrain期間で `C0` を推定
3. 期間全体でシグナル作成
4. pretrain翌年以降でバックテスト評価
5. returns CSVを `outputs/lead_lag_returns.csv` に保存
