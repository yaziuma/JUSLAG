# シグナルスケール × Regime 分析レポート

生成日: 2026-05-11  
分析期間: 2018-09-27 〜 2026-05-08 (1788日)  
base_long_threshold: 0.1 / base_short_threshold: -0.1  
window_l=60, k=3, lambda=0.9  

---

## 1. 見送り原因の結論（2026-05-11 時点）

### 2026-05-08 当日の事実
- 最大 LONG signal = 0.0787（食品 1617.T）
- 固定閾値 0.10 への不足 = **0.021**（閾値の 21% 手前）
- vol_regime: **high_vol**、trend_regime: sideways

### 実データによる仮説検証
| 仮説 | 検証結果 |
|---|---|
| high_vol で signal 絶対値が縮む | **否定**: high_vol の signal_abs_mean = 0.0567 > low_vol 0.0509 |
| high_vol で no_long 発生率が高い | **軽度確認**: 54.8% (high_vol) vs 47.6% (mid_vol)。差は約 7pp |
| z 正規化圧縮が主因 | **否定**: 1788 日バックテストで高_vol の signal スケールは他 regime と大差なし |
| 固定閾値 0.10 が厳しすぎる | **確認**: 全 regime で tradeable 率 47.4%（見送りが過半数）|

### 結論
**主因は「z 正規化圧縮」ではなく「固定閾値 0.10 が全局面で厳しすぎること」。**
2026-05-08 の見送りは high_vol 特有の問題ではなく、signal_max=0.0787 が閾値 0.10 に 0.021 届かなかった通常事象。
相場実態（全面高）と戦略判断（相対強弱シグナルが閾値未満）は矛盾しない。

---

## 2. vol_regime 別シグナルスケール

| vol_regime | 日数 | signal絶対値平均 | signal中央値平均 | LONG上位1位平均 | tradeable率(固定) | tradeable率(adaptive) | no_long率(固定) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **high_vol** | 462 | 0.0567 | -0.0001 | 0.1224 | 44.4% | 65.8% | 54.8% |
| **low_vol** | 417 | 0.0509 | -0.0002 | 0.1075 | 43.2% | 33.8% | 55.2% |
| **mid_vol** | 909 | 0.0605 | 0.0001 | 0.1292 | 50.9% | 50.9% | 47.6% |

---

## 3. trend_regime 別シグナルスケール

| trend_regime | 日数 | signal絶対値平均 | LONG上位1位平均 | tradeable率(固定) | tradeable率(adaptive) |
|---|---:|---:|---:|---:|---:|
| **downtrend** | 264 | 0.0646 | 0.1392 | 53.4% | 63.6% |
| **sideways** | 935 | 0.0546 | 0.1165 | 44.4% | 46.1% |
| **uptrend** | 589 | 0.0583 | 0.1241 | 49.6% | 52.5% |

---

## 4. trend × vol クロス集計

| trend | vol | 日数 | tradeable率(固定) | tradeable率(adaptive) | LONG上位1位平均 |
|---|---|---:|---:|---:|---:|
| downtrend | high_vol | 134 | 46.3% | 66.4% | 0.1397 |
| downtrend | low_vol | 29 | 51.7% | 51.7% | 0.1287 |
| downtrend | mid_vol | 101 | 63.4% | 63.4% | 0.1416 |
| sideways | high_vol | 170 | 41.8% | 64.7% | 0.1154 |
| sideways | low_vol | 244 | 39.8% | 30.3% | 0.0993 |
| sideways | mid_vol | 521 | 47.4% | 47.4% | 0.1250 |
| uptrend | high_vol | 158 | 45.6% | 66.5% | 0.1154 |
| uptrend | low_vol | 144 | 47.2% | 36.1% | 0.1173 |
| uptrend | mid_vol | 287 | 53.0% | 53.0% | 0.1324 |

---

## 5. 固定閾値 vs Adaptive 閾値（vol 別）

Adaptive threshold 設定:

| vol_regime | fixed | adaptive |
|---|---:|---:|
| low_vol | ±0.10 | ±0.12 |
| mid_vol | ±0.10 | ±0.10 |
| high_vol | ±0.10 | ±0.06 |

| vol_regime | adopted_long(固定) | adopted_long(adaptive) | tradeable率(固定) | tradeable率(adaptive) |
|---|---:|---:|---:|---:|
| **high_vol** | 1.70 | 2.56 | 44.4% | 65.8% |
| **low_vol** | 1.65 | 1.30 | 43.2% | 33.8% |
| **mid_vol** | 1.97 | 1.97 | 50.9% | 50.9% |

---

## 6. 固定閾値候補の比較

| 閾値 | tradeable率 | no_long率 | no_short率 | avg_adopted_long | avg_adopted_short |
|---|---:|---:|---:|---:|---:|
| ±0.10 | 47.4% | 51.2% | 51.5% | 1.83 | 1.83 |
| ±0.08 | 55.6% | 43.2% | 43.0% | 2.16 | 2.16 |
| ±0.06 | 66.3% | 32.4% | 32.1% | 2.59 | 2.61 |
| ±0.05 | 72.4% | 26.3% | 26.7% | 2.83 | 2.84 |

---

## 7. 導入判断

### Adaptive threshold 採用条件チェック

- [ x ] high_vol tradeable率が改善: 44.4% → 65.8% (+21.4%)
- [ ? ] gross/net リターン比較 → バックテストで別途検証要
- [ ? ] MDD 比較 → バックテストで別途検証要

**結論（暫定）:**

- Adaptive は high_vol を +21.4pp 改善するが、low_vol を -9.4pp 悪化させる
- 代替案: 全 regime 一律 **±0.08** → tradeable率 55.6%（+8.2pp）で low_vol を犠牲にしない
- Adaptive の採用可否はバックテスト gross/net/MDD 比較後に最終判断
- `adaptive_threshold: true` を `config/app.yaml` に設定することで実験的に有効化可能

---

## 8. 残る限界

- 本スクリプトは signal 分布のみを分析しており、gross/net リターン・MDD との比較はない
- adaptive threshold がノイズ日を拾ってリターン悪化する可能性は別途バックテストで検証要
- ログ期間が短い（現在 45 行）ため regime 偏りの統計精度は低い
- z 正規化圧縮の根本解決（シグナル出力の rescaling）は別途検討余地あり