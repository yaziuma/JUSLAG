# 引き継ぎメモ（2026-09-16）

## 現状

- 元論文: 中川ほか、SIG-FIN-036-13。PDFは`papers/SIG-FIN-036-13.pdf`にローカル配置し、`papers/`はGit管理対象外。
- 論文準拠PCAと現行メタ戦略の比較を日次レポート/サイトに追加。詳細は`paper_implementation_review_20260916.md`。
- 1629.Tの2026-03-30/31はYahooキャッシュで分割調整が二重適用された。運用会社の1:500分割開示と株探・みんかぶのOHLCで照合し、`data_loader.repair_known_bad_prices()`で読み込み時のみ修復。キャッシュ原本は変更しない。
- 外部独立実装`akihidem/subspace-pca-leadlag`（commit `3bc7147b7783cea117aaaa109352a922f12089a5`）を同じローカル調整価格・共通取引日・PCA設定で走らせた。1,106日の日次グロス損益はJUSLAGと全日一致。グロス年率+6.454%、両側グロス2を毎日寄り→引け往復し5bps/sideを課すとネット年率-43.946%。スクリプトは`scripts/reports/compare_external_pca.py`、詳細は`external_paper_implementations_20260916.md`。
- JUSLAG通常の日次比較では、論文準拠版1104日でグロス年率+8.31%、ネット-42.09%。現行メタ版726日でグロス+26.65%、ネット-23.03%。結果は`/tmp/juslag_repaired_compare/reports/2026-09-16.json`（一時ファイル）。外部との6.454%の差は主に市場別の前日比と共通日での前日比の作り方の違い。比較期間・算式を混同しない。
- 外部実装はコストを`Σ|w_t-w_(t-1)|`で計算。寄り建て・引け全決済なら`2Σ|w_t|=4`が必要で、外部のネット成績は日中往復売買を過小計上する。論文のグロス値とは別。
- 保有1/2/3/5日のイベントスタディでは、修復後ネット平均は順に-16.69/-12.47/-12.28/-4.39bps。重複保有窓であり資金制約付きバックテストではない。`signal_horizon_validation_20260916.md`の旧数値には更新注記あり。

## 次の優先事項

1. レジーム分位点は20観測以降のexpandingで当日までの値だけを使用するよう修正済み。未来データ追加に対する不変性テストを追加。
2. バックテストのメタ戦略は利益対象の次JP行の寄りgapを参照するよう修正済み。日次では対象日Openがない場合に過去日gapを代用せず、未観測・見送りとする。ただし08:00 JSTの実運用で寄りgapルールを満たせない根本問題は残る。09:00以降の執行設計か、事前観測できる情報へのルール変更が必要。
3. 日米休日・タイムゾーンを明示し、シグナル日と次の日本執行日を時刻ベースで対応付ける。価格リターンの共通日化順序も統一する。
4. 実際の寄り/引け約定、板、売建在庫、HYPER料を記録し、5bps/side仮定を実測で検証する。
5. 低回転・保有持越し案は別戦略として、資金・同時建玉・コストを含む独立ウォークフォワードで評価する。

## 再実行・検証

- 外部コードを`/tmp/subspace-pca-leadlag`にcloneした場合: `.venv/bin/python scripts/reports/compare_external_pca.py --external-repo /tmp/subspace-pca-leadlag`
- 保有期間: `.venv/bin/python scripts/reports/validate_signal_horizons.py`
- テスト: `.venv/bin/pytest -q`（最終実行218 passed）。ruffと`git diff --check`も通過。
- 現時点で発注・実資金投入は不可。Judgeのメタ成績は先読みとギャップ日付不整合のため信頼しない。
