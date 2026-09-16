# 均等化口数（normalized_lots）の設計意図

## 概要

執行計画（LONG/SHORT）の各銘柄に表示される「均等化口数」は、**全銘柄の購入金額を揃えること**を目的として計算された参考口数です。

口数の数値が大きいこと自体は異常ではありません。**投資金額（口数 × 終値）が他銘柄と同程度であれば正常です。**

---

## 計算式

```
目標金額 = max(各銘柄の latest_price_jpy × trading_unit)
単位ブロック数 = max(1, round(目標金額 / (latest_price_jpy × trading_unit)))
均等化口数 = 単位ブロック数 × trading_unit

均等化購入金額 = 均等化口数 × latest_price_jpy
```

- `trading_unit`: 東証が定める銘柄別売買単位（口）
- `latest_price_jpy`: 各銘柄の直近終値（円）

---

## 具体例

| 銘柄 | 終値 | 均等化口数 | 均等化購入金額 |
|------|------|-----------|--------------|
| 1624.T（機械）| 90,540円 | **1口** | 90,540円 |
| 1631.T（銀行）| 33,420円 | 3口 | 100,260円 |
| 1629.T（商社・卸売）| 280円 | **320口** | 89,600円 |

→ 1629.T は口数が320口と大きいが、**購入金額は89,600円で他銘柄と同程度**。これは正常な計算結果です。2026-03-30以降の売買単位10口にも適合します。

---

## 口数が極端に大きくなるケース

**株式分割（ETF分割）が発生した場合**、価格が大幅に下落するため均等化口数が急増することがあります。

### 実例：1629.T（NEXT FUNDS 商社・卸売業 ETF）

| 日付 | 終値 | 状況 |
|------|------|------|
| 2026-03-27 | 144,300円 | 分割前 |
| 2026-03-30 | 284円 | **約500:1分割後** |

分割後は10口単位で `round(90,540 / (284 × 10)) × 10 ≈ 320口` となる。口数は増えるが投資金額は同水準であり、**これは設計どおりの動作です。**

---

## よくある誤解

### ❌ 「320口は異常に多い → バグでは？」

→ **バグではありません。** 口数ではなく購入金額を比較してください。

### ❌ 「口数が多すぎるから上限を設けるべき」

→ **上限を設けると購入金額が不均等になります。** 例えば上限100口にすると 100 × 280円 = 28,000円となり、他銘柄の90,000〜100,000円と大きく乖離します。均等投資の意味がなくなるため、上限は設けません。

---

## 実装箇所

`src/juslag/services/daily_signal.py` の `normalize_execution_plan_lots`：

```python
# 最も高い最低購入金額へ揃え、銘柄別売買単位の倍数で口数を計算
all_entries = long_plan + short_plan
valid_min_purchases = [e["min_purchase_jpy"] for e in all_entries if e["min_purchase_jpy"] is not None]
if valid_min_purchases:
    target_purchase = max(valid_min_purchases)
    for entry in all_entries:
        price = entry["latest_price_jpy"]
        trading_unit = entry["min_lot"]
        if price is not None and price > 0:
            unit_blocks = max(1, round(target_purchase / (price * trading_unit)))
            norm_lots = unit_blocks * trading_unit
            entry["normalized_lots"] = norm_lots
            entry["normalized_purchase_jpy"] = round(norm_lots * price)
```

---

## APIレスポンス

`GET /api/daily-signal` → `execution_plan.long[]` / `execution_plan.short[]` の各要素：

```json
{
  "ticker": "1629.T",
  "sector": "商社・卸売",
  "latest_price_jpy": 280,
  "normalized_lots": 320,
  "normalized_purchase_jpy": 89600
}
```
