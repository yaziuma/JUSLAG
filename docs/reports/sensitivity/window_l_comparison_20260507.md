# Window L 感度分析レポート（L=15/30/60/90/120）

**作成日**: 2026-05-07  
**目的**: 主成分分析の窓幅 Window L のみを変えた場合の戦略パフォーマンス比較  
**その他パラメータ**: すべてデフォルト値（commission=0bps / slippage=1bps / borrow=0% / tax=20.315% / quantile_q=0.3 / k=3 / λ=0.9）

---

## 1. 共通パラメータ

| パラメータ | 値 |
|---|---|
| sample_start | 2018-07-01 |
| pretrain_end | 2021-12-31 |
| eval_start | 2022-01-01 |
| k_factors | 3 |
| lambda_reg | 0.9 |
| quantile_q | 0.3 |
| min_long_signal | 0.10 |
| max_short_signal | -0.10 |
| price_mode | raw |
| commission_bps_per_side | 0.0 |
| slippage_bps_per_side | 1.0 |
| short_borrow_rate_annual | 0.0% |
| tax_rate | 20.315% |
| tax_model | annual_net |

---

## 2. パフォーマンス比較表

| L | Gross AR% | Gross R/R | Gross MDD% | Net AT AR% | Net AT R/R | Net AT MDD% | cost_drag% | tax_drag% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **15** | 29.9% | 2.35 | -8.1% | 15.9% | 1.25 | -13.7% | 9.93% | 4.05% |
| **30** | 31.5% | 2.31 | -7.0% | 17.2% | 1.26 | -9.2% | 9.94% | 4.39% |
| **60** | 39.9% | 3.33 | -10.3% | 23.9% | 1.86 | -15.0% | 9.91% | 6.09% |
| **90** | 33.2% | 2.65 | -9.8% | 18.5% | 1.48 | -14.7% | 10.03% | 4.71% |
| **120** | 29.8% | 2.26 | -13.0% | 15.8% | 1.19 | -17.0% | 9.96% | 4.04% |

---

## 3. Judge 採点比較

| L | profitability | stability | cost_resilience | executability | data_reliability | **total** | decision |
|---|---:|---:|---:|---:|---:|---:|---|
| 15 | 30 | 20 | 3 | 10 | 15 | **78** | **PASS** |
| 30 | 30 | 25 | 3 | 10 | 15 | **83** | **PASS** |
| 60 | 30 | 18 | 0 | 10 | 15 | **73** | **HOLD** |
| 90 | 30 | 20 | 3 | 10 | 15 | **78** | **PASS** |
| 120 | 30 | 18 | 3 | 10 | 15 | **76** | **PASS** |

---

## 4. 詳細分析

### 4-1. リターン・リスク特性

**L=60 がグロスで突出している。**
Gross AR 39.9%・R/R 3.33 は全 L 中最高で、他より 6〜10pt 高い。
PCA の固有ベクトルを推定するためには適度な窓幅が必要であり、L=60（約3ヶ月）がその最適点である可能性が高い。短すぎる L=15・30 はノイズに敏感でシグナルが不安定、長すぎる L=90・120 は市場構造変化への追従が遅れる。

ただし **税引後では L=30 が MDD -9.2% と最も浅く安定性が高い**。
L=60 は税引後 MDD -15.0% まで深まり、税コスト負担（tax_drag 6.09%）も他より重い。

### 4-2. コスト・税効率

**cost_drag はどの L でも約 9.9〜10.0% で、L に依存しない。**
slippage 1bps という固定コストが主因であり、窓幅を変えても変化しない。

一方 **tax_drag は L=60 のみ 6.09% と突出して高く**、他の L は 4.0〜4.7%。
L=60 の高い Gross AR（39.9%）が課税対象利益を押し上げるためであり、高リターン戦略ほど税負担が重くなる構造的な問題を示している。

### 4-3. Judge 採点の考察

| 評価軸 | 最優 | 最劣 |
|---|---|---|
| 総合スコア | L=30（83点） | L=60（73点） |
| Gross パフォーマンス | L=60（R/R 3.33） | L=120（R/R 2.26） |
| 安定性（MDD） | L=30（-7.0%） | L=120（-13.0%） |
| 税効率 | L=120（tax_drag 4.04%） | L=60（tax_drag 6.09%） |

L=60 が HOLD に留まった理由は **tax_drag 6.09% が閾値を超え cost_resilience=0** になったため。
Gross では圧倒的に優れるが、tax_drag が HIGH_COST_DRAG と同時発生し critical_warn となり PASS を阻んでいる。

---

## 5. 考察・推奨

### 運用目的別推奨

| 目的 | 推奨 L | 根拠 |
|---|---|---|
| **グロスリターン最大化** | **L=60** | Gross AR 39.9%・R/R 3.33 で全 L 中最高 |
| **Judge スコア・安定性重視** | **L=30** | 総合スコア 83点・MDD -9.2%・PASS判定 |
| **税引後リターンと安定性のバランス** | **L=30** | Net AT AR 17.2% かつ MDD -9.2% と最も浅い |
| **市場追従・長期安定** | **L=90** | L=60 より MDD が浅く（-14.7%）スコアも 78点 |

### 総合推奨: L=30

税引後・安定性・Judge スコアの三拍子が揃っており、実運用上の信頼性が最も高い。
MDD の浅さ（-9.2%）と PASS 判定（83点）は実用上の優位性として大きい。

**L=60 について**:
グロスパフォーマンスは明らかに最優位。ただし tax_drag の高さが Judge 採点上の弱点。
quantile_q の引き上げによるターンオーバー削減、または tax_model の見直しが PASS 到達への近道。

---

## 6. 付録：スコア内訳

| L | profitability_components | stability_components | cost_resilience_components | reasons |
|---|---|---|---|---|
| 15 | ar=30, rr_pen=0 | mdd=20, rr_pen=0 | mkt=0, tax=3 | HIGH_COST_DRAG |
| 30 | ar=30, rr_pen=0 | mdd=25, rr_pen=0 | mkt=0, tax=3 | HIGH_COST_DRAG |
| 60 | ar=30, rr_pen=0 | mdd=18, rr_pen=0 | mkt=0, tax=0 | HIGH_COST_DRAG, HIGH_TAX_DRAG |
| 90 | ar=30, rr_pen=0 | mdd=20, rr_pen=0 | mkt=0, tax=3 | HIGH_COST_DRAG |
| 120 | ar=30, rr_pen=0 | mdd=18, rr_pen=0 | mkt=0, tax=3 | HIGH_COST_DRAG |

**全 L 共通の課題**: `market_cost_score=0`（cost_drag 約10% が閾値 4% を大きく超過）。
slippage=1bps でも窓幅に依存しないコスト構造であり、構造的改善（quantile_q 引き上げ・ターンオーバー抑制）が必要。
