# 局面依存方向性検証レポート（約1年（252営業日）版）

生成日: 2026-04-26

## 1. 目的

約1年（252営業日）の direction flip 検証で観察された局面依存パターンを切り分ける。
**「どんな局面で現行方向 / 反転方向が有利か」** を trend / vol / rotation の3軸で分析する。

## 2. 分析条件

| 項目 | 値 |
| --- | --- |
| 対象期間 | 2025-03-31 〜 2026-04-24 |
| 総日数 | 252 日 |
| price_mode | raw |
| fill_policy | strict |
| quantile_q | 0.3 |
| window_l | 60 |
| min_long_signal | 0.1 |
| max_short_signal | -0.1 |

### 局面分類ルール

| 局面軸 | 分類方法 |
| --- | --- |
| trend | JP等重平均の20日累積リターン: >3% → uptrend / <-3% → downtrend / その他 → sideways |
| vol | JP等重平均の20日 realized vol の全期間分位: 上位25% → high_vol / 下位25% → low_vol |
| rotation | signal の横断的std の全期間分位: 上位25% → strong_rotation / 下位25% → weak_rotation |

## 3. 局面別 現行 vs 反転 比較

### 3-1. 市場方向（trend）別

| 局面 | 方向 | 採用件数 | 平均損益% | 勝率 | 疑似累積損益% | 最大DD% |
| --- | --- | --- | --- | --- | --- | --- |
| uptrend | 現行方向 | 60 | +0.244% | 61.7% | +15.44% | -5.26% |
| uptrend | 反転方向 | 60 | -0.230% | 38.3% | -13.17% | -11.76% |
| sideways | 現行方向 | 36 | +0.008% | 58.3% | +0.09% | -8.15% |
| sideways | 反転方向 | 34 | -0.028% | 41.2% | -1.16% | -7.01% |
| downtrend | 現行方向 | 12 | -0.323% | 50.0% | -3.91% | -5.67% |
| downtrend | 反転方向 | 12 | +0.656% | 58.3% | +8.01% | -2.86% |

### 3-2. ボラティリティ（vol）別

| 局面 | 方向 | 採用件数 | 平均損益% | 勝率 | 疑似累積損益% | 最大DD% |
| --- | --- | --- | --- | --- | --- | --- |
| low_vol | 現行方向 | 20 | +0.078% | 70.0% | +1.51% | -2.65% |
| low_vol | 反転方向 | 19 | -0.050% | 31.6% | -1.00% | -3.55% |
| mid_vol | 現行方向 | 45 | +0.173% | 57.8% | +7.89% | -5.26% |
| mid_vol | 反転方向 | 46 | -0.171% | 41.3% | -7.75% | -12.47% |
| high_vol | 現行方向 | 43 | +0.041% | 55.8% | +1.38% | -11.66% |
| high_vol | 反転方向 | 41 | +0.046% | 46.3% | +1.49% | -10.98% |

### 3-3. ローテーション強度（rotation）別

| 局面 | 方向 | 採用件数 | 平均損益% | 勝率 | 疑似累積損益% | 最大DD% |
| --- | --- | --- | --- | --- | --- | --- |
| weak_rotation | 現行方向 | 0 | — | — | — | — |
| weak_rotation | 反転方向 | 0 | — | — | — | — |
| mid_rotation | 現行方向 | 52 | +0.239% | 69.2% | +12.99% | -6.28% |
| mid_rotation | 反転方向 | 50 | -0.165% | 32.0% | -8.17% | -14.83% |
| strong_rotation | 現行方向 | 56 | -0.024% | 50.0% | -1.74% | -9.28% |
| strong_rotation | 反転方向 | 56 | +0.024% | 50.0% | +0.94% | -8.39% |

## 4. 複合局面比較

| 複合局面 | 方向 | 採用件数 | 平均損益% | 勝率 | 疑似累積損益% |
| --- | --- | --- | --- | --- | --- |
| downtrend × high_vol | 現行方向 | 12 | -0.323% | 50.0% | -3.91% |
| downtrend × high_vol | 反転方向 | 12 | +0.656% | 58.3% | +8.01% |
| downtrend × mid_rotation | 現行方向 | 5 | -0.495% | 40.0% | -2.48% |
| downtrend × mid_rotation | 反転方向 | 5 | +1.295% | 80.0% | +6.59% |
| downtrend × strong_rotation | 現行方向 | 7 | -0.200% | 57.1% | -1.46% |
| downtrend × strong_rotation | 反転方向 | 7 | +0.200% | 42.9% | +1.33% |
| sideways × high_vol | 現行方向 | 14 | -0.501% | 28.6% | -6.88% |
| sideways × high_vol | 反転方向 | 13 | +0.443% | 69.2% | +5.81% |
| sideways × low_vol | 現行方向 | 10 | -0.013% | 80.0% | -0.17% |
| sideways × low_vol | 反転方向 | 9 | +0.081% | 22.2% | +0.70% |
| sideways × mid_rotation | 現行方向 | 16 | +0.100% | 68.8% | +1.56% |
| sideways × mid_rotation | 反転方向 | 14 | -0.162% | 28.6% | -2.29% |
| sideways × mid_vol | 現行方向 | 12 | +0.621% | 75.0% | +7.67% |
| sideways × mid_vol | 反転方向 | 12 | -0.621% | 25.0% | -7.23% |
| sideways × strong_rotation | 現行方向 | 20 | -0.065% | 50.0% | -1.45% |
| sideways × strong_rotation | 反転方向 | 20 | +0.065% | 50.0% | +1.16% |
| uptrend × high_vol | 現行方向 | 17 | +0.743% | 82.4% | +13.30% |
| uptrend × high_vol | 反転方向 | 16 | -0.733% | 18.8% | -11.19% |
| uptrend × low_vol | 現行方向 | 10 | +0.169% | 60.0% | +1.68% |
| uptrend × low_vol | 反転方向 | 10 | -0.169% | 40.0% | -1.69% |
| uptrend × mid_rotation | 現行方向 | 31 | +0.429% | 74.2% | +14.10% |
| uptrend × mid_rotation | 反転方向 | 31 | -0.402% | 25.8% | -11.82% |
| uptrend × mid_vol | 現行方向 | 33 | +0.011% | 51.5% | +0.20% |
| uptrend × mid_vol | 反転方向 | 34 | -0.012% | 47.1% | -0.55% |
| uptrend × strong_rotation | 現行方向 | 29 | +0.047% | 48.3% | +1.18% |
| uptrend × strong_rotation | 反転方向 | 29 | -0.047% | 51.7% | -1.53% |

## 5. LONG / SHORT 寄与の局面別比較

### 5-1. trend 別 LONG/SHORT 寄与

| 局面 | 方向 | 採用日平均LONG寄与% | 採用日平均SHORT寄与% |
| --- | --- | --- | --- |
| uptrend | 現行方向 | +0.040% | +0.204% |
| uptrend | 反転方向 | -0.205% | -0.025% |
| sideways | 現行方向 | -0.211% | +0.219% |
| sideways | 反転方向 | -0.232% | +0.204% |
| downtrend | 現行方向 | -0.481% | +0.159% |
| downtrend | 反転方向 | +0.120% | +0.536% |

### 5-2. vol 別 LONG/SHORT 寄与

| 局面 | 方向 | 採用日平均LONG寄与% | 採用日平均SHORT寄与% |
| --- | --- | --- | --- |
| low_vol | 現行方向 | -0.070% | +0.147% |
| low_vol | 反転方向 | -0.155% | +0.105% |
| mid_vol | 現行方向 | +0.010% | +0.163% |
| mid_vol | 反転方向 | -0.161% | -0.010% |
| high_vol | 現行方向 | -0.234% | +0.274% |
| high_vol | 反転方向 | -0.206% | +0.252% |

## 6. 異常日一覧（|反転−現行| 差分上位）

差分の絶対値が 0.5% 超の日を差分降順で表示（最大20件）。

| 日付 | 現行損益% | 反転損益% | 差分% | trend | vol | rotation |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-02-12 | +3.631% | -3.631% | -7.263% | uptrend | high_vol | strong_rotation |
| 2025-04-03 | +3.294% | -3.294% | -6.588% | sideways | high_vol | strong_rotation |
| 2025-04-09 | -2.800% | +2.800% | +5.600% | downtrend | high_vol | strong_rotation |
| 2026-03-06 | +2.327% | -2.327% | -4.653% | uptrend | high_vol | mid_rotation |
| 2026-01-30 | +2.132% | -2.132% | -4.263% | uptrend | mid_vol | mid_rotation |
| 2026-02-04 | -2.073% | +2.073% | +4.146% | uptrend | mid_vol | strong_rotation |
| 2026-02-05 | -2.004% | +2.004% | +4.007% | uptrend | mid_vol | strong_rotation |
| 2026-04-09 | -1.968% | +1.968% | +3.937% | downtrend | high_vol | mid_rotation |
| 2025-04-16 | +1.859% | -1.859% | -3.718% | downtrend | high_vol | strong_rotation |
| 2025-11-17 | +1.775% | -1.775% | -3.550% | uptrend | mid_vol | strong_rotation |
| 2025-10-01 | -1.715% | +1.715% | +3.430% | sideways | low_vol | strong_rotation |
| 2026-03-24 | +0.000% | +3.347% | +3.347% | downtrend | high_vol | mid_rotation |
| 2026-01-05 | +1.635% | -1.635% | -3.271% | uptrend | mid_vol | strong_rotation |
| 2025-12-11 | +1.632% | -1.632% | -3.263% | sideways | mid_vol | mid_rotation |
| 2025-05-08 | +1.607% | -1.607% | -3.214% | uptrend | high_vol | mid_rotation |
| 2025-10-10 | +1.594% | -1.594% | -3.187% | sideways | mid_vol | strong_rotation |
| 2025-09-19 | -1.585% | +1.585% | +3.169% | sideways | low_vol | strong_rotation |
| 2026-04-23 | -1.537% | +1.537% | +3.074% | downtrend | high_vol | strong_rotation |
| 2026-04-20 | -1.527% | +1.527% | +3.054% | sideways | high_vol | strong_rotation |
| 2026-03-09 | -1.510% | +1.510% | +3.020% | sideways | high_vol | strong_rotation |

## 7. 所見

### 7-1. 反転優位になりやすい局面

- downtrend（trend）

### 7-2. 現行優位になりやすい局面

- uptrend（trend）
- low_vol（vol）
- mid_vol（vol）
- mid_rotation（rotation）

### 7-3. 直近の反転優位について

- 2026年4月異常日の局面構成: trend: {'downtrend': 2, 'sideways': 1}, vol: {'high_vol': 3}
- 反転優位が急拡大した背景として以下が考えられる:
  - **downtrend × high_vol** 局面への突入（日米関税ショック等）
  - signal の学習データ（過去60日）が従来局面に過適応していた可能性

## 8. 結論

### 判定: **局面注意フラグを入れる価値あり**

下落局面 / 高ボラ局面では反転方向が優位な傾向が確認された。

### 次にやるべきこと

- [ ] downtrend / high_vol 判定ロジックを daily-signal に追加（警告フラグのみ）
- [ ] 上記局面での signal × next_oc を個別検証
- [ ] 局面フラグが True の日は「注意: 現行方向の信頼性低下」を UI に表示
- [ ] 本番ロジック変更前に 6ヶ月以上のフォワード検証を実施

本レポート生成日: 2026-04-26
