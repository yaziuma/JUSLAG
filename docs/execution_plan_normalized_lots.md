# 均等化口数（normalized_lots）の設計意図

## 概要

執行計画（LONG/SHORT）の各銘柄に表示される「均等化口数」は、**全銘柄の購入金額を揃えること**を目的として計算された参考口数です。

口数の数値が大きいこと自体は異常ではありません。**投資金額（口数 × 終値）が他銘柄と同程度であれば正常です。**

---

## 計算式

```
均等化口数 = round(max_lot_price / latest_price_jpy)
均等化口数 = max(1, 均等化口数)  # 最小1口

均等化購入金額 = 均等化口数 × latest_price_jpy
```

- `max_lot_price`: 執行計画内の全銘柄（LONG+SHORT）のうち、最も高い終値（円）
- `latest_price_jpy`: 各銘柄の直近終値（円）

---

## 具体例

| 銘柄 | 終値 | 均等化口数 | 均等化購入金額 |
|------|------|-----------|--------------|
| 1624.T（機械）| 90,540円 | **1口** | 90,540円 |
| 1631.T（銀行）| 33,420円 | 3口 | 100,260円 |
| 1629.T（商社・卸売）| 280円 | **323口** | 90,440円 |

→ 1629.T は口数が323口と大きいが、**購入金額は90,440円で他銘柄と同程度**。これは正常な計算結果です。

---

## 口数が極端に大きくなるケース

**株式分割（ETF分割）が発生した場合**、価格が大幅に下落するため均等化口数が急増することがあります。

### 実例：1629.T（NEXT FUNDS 商社・卸売業 ETF）

| 日付 | 終値 | 状況 |
|------|------|------|
| 2026-03-27 | 144,300円 | 分割前 |
| 2026-03-30 | 284円 | **約500:1分割後** |

分割後は `round(90,540 / 284) ≈ 319口` となる。口数は増えるが投資金額は同水準であり、**これは設計どおりの動作です。**

---

## よくある誤解

### ❌ 「323口は異常に多い → バグでは？」

→ **バグではありません。** 口数ではなく購入金額を比較してください。

### ❌ 「口数が多すぎるから上限を設けるべき」

→ **上限を設けると購入金額が不均等になります。** 例えば上限100口にすると 100 × 280円 = 28,000円となり、他銘柄の90,000〜100,000円と大きく乖離します。均等投資の意味がなくなるため、上限は設けません。

---

## 実装箇所

`webui/main.py` の `daily_signal` エンドポイント内：

```python
# 1番高いセクターの最低購入金額(10口)に金額を合わせた口数を計算
all_entries = long_plan + short_plan
valid_prices = [e["latest_price_jpy"] for e in all_entries if e["latest_price_jpy"] is not None]
if valid_prices:
    max_lot_price = max(valid_prices)
    for entry in all_entries:
        price = entry["latest_price_jpy"]
        if price is not None and price > 0:
            norm_lots = max(1, round(max_lot_price / price))
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
  "normalized_lots": 323,
  "normalized_purchase_jpy": 90440
}
```
