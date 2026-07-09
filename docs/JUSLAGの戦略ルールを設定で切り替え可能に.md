# 実装指示書：JUSLAG メタ戦略ルール切替・説明ページ追加

## 1. 目的

JUSLAG において、固定の戦略ルールだけでなく、複数のメタ戦略ルールを設定で切り替えられるようにする。

現在の検証では、単純な `GapOvht除外OC` や `LGap除外OC` だけでなく、以下のような条件付きメタ戦略が候補になっている。

```text
- GapOvht + open_gap制限 + weak_rotation除外 + short_gap過熱時LONG反転
- GapOvht + シグナル強度0.3以上 + 高ボラgap時LONG反転
- GapOvht + 高ボラ/強rotation + short_gap過熱時SHORT単独
- GapOvht + gap過熱時LGap切替
- rolling3 による年次ルール選択
```

これらをハードコードで増やすのではなく、**ルール単位でカプセル化**し、設定値から選択できる構造にする。

また、運用者がルールの意味を確認できるよう、UI に **日本語のルール説明ページ** を追加する。

---

# 2. 実装範囲

## 2.1 対象機能

以下を対象とする。

| 区分     | 内容                       |
| ------ | ------------------------ |
| バックエンド | ルール定義、ルール選択、日次シグナルへの適用   |
| バックテスト | 選択されたメタ戦略ルールでのバックテスト     |
| UI     | ルール選択設定、現在の採用ルール表示       |
| 説明ページ  | 各ルールの日本語説明、条件、切替先、注意点    |
| 履歴     | 採用されたルールID、ルール名、切替理由を保存  |
| コード品質  | ルールをクラスまたは関数オブジェクトでカプセル化 |

---

# 3. 設計方針

## 3.1 ルールは必ずカプセル化する

禁止する実装。

```python
if rule_id == "rule_406":
    ...
elif rule_id == "rule_399":
    ...
elif rule_id == "rule_13":
    ...
```

これはやらない。ざっこい分岐地獄になる。

やるべき構造。

```text
StrategyRule
  ├─ Rule406_OpenGapRotShortFlip
  ├─ Rule399_StrongSignalHighVolFlip
  ├─ Rule13_HighVolRotationShortOnly
  ├─ Rule87_LGapSwitch
  └─ Rolling3RuleSelector
```

各ルールは、共通インターフェースを持つ。

---

# 4. 推奨ディレクトリ構成

既存構成に合わせて調整してよいが、概念的には以下。

```text
backend/
  app/
    strategies/
      __init__.py
      base.py
      context.py
      decision.py
      registry.py

      primitive/
        __init__.py
        curr_oc.py
        gap_ovht.py
        lgap.py
        long_flip.py
        short_only.py
        curr_cc.py

      meta/
        __init__.py
        rule_406.py
        rule_399.py
        rule_13.py
        rule_87.py
        rolling3_selector.py

      descriptions/
        rules_ja.py

    routers/
      strategy_rules.py

    schemas/
      strategy_rules.py

frontend/
  src/
    pages/
      StrategyRuleSettingsPage.tsx
      StrategyRuleExplanationPage.tsx

    components/
      strategy/
        StrategyRuleSelector.tsx
        StrategyRuleCard.tsx
        StrategyDecisionPreview.tsx
```

---

# 5. ドメインモデル

## 5.1 StrategyContext

ルール判定に使う入力値をまとめる。

```python
from dataclasses import dataclass
from typing import Literal, Optional


TrendRegime = Literal["uptrend", "downtrend", "sideways"]
VolRegime = Literal["high_vol", "mid_vol", "low_vol"]
RotationRegime = Literal["strong_rotation", "mid_rotation", "weak_rotation"]

PrimitiveStrategyId = Literal[
    "curr_oc",
    "gap_ovht_oc",
    "lgap_oc",
    "long_flip_oc",
    "short_only_oc",
    "curr_cc",
    "skip",
]


@dataclass(frozen=True)
class StrategyContext:
    signal_date: str

    candidate_signal_strength: Optional[float]

    open_gap: Optional[float]
    long_gap: Optional[float]
    short_gap: Optional[float]

    trend_regime: Optional[TrendRegime]
    vol_regime: Optional[VolRegime]
    rotation_regime: Optional[RotationRegime]
```

注意点。

* `open_gap` は `jp_next_open_gap_mean` 相当
* `long_gap` は `jp_long_gap_mean` 相当
* `short_gap` は `jp_short_gap_mean` 相当
* `candidate_signal_strength` は候補シグナル強度
* `None` が来る可能性を考慮する
* `jp_oc_mean` や引け後の損益結果系は、ルール判定に使わない

---

## 5.2 StrategyDecision

ルール判定結果を返す。

```python
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class StrategyDecision:
    selected_strategy: str
    rule_id: str
    rule_name_ja: str

    action: str
    reason_ja: str

    default_strategy: Optional[str] = None
    override_strategy: Optional[str] = None
    matched_filter: Optional[str] = None
    matched_override: Optional[str] = None
```

`action` は以下。

```text
execute
skip
override
```

例。

```python
StrategyDecision(
    selected_strategy="long_flip_oc",
    rule_id="rule_406",
    rule_name_ja="GapOvht + 寄りgap制限 + 弱rotation除外 + SHORT過熱時LONG反転",
    action="override",
    reason_ja="SHORT側gapが1.0%を超えたため、LONG反転OCへ切り替え",
    default_strategy="gap_ovht_oc",
    override_strategy="long_flip_oc",
    matched_filter="abs_open_gap <= 1.5% and rotation != weak_rotation",
    matched_override="abs_short_gap > 1.0%",
)
```

---

# 6. 共通インターフェース

## 6.1 StrategyRule

```python
from abc import ABC, abstractmethod
from app.strategies.context import StrategyContext
from app.strategies.decision import StrategyDecision


class StrategyRule(ABC):
    rule_id: str
    rule_name_ja: str
    description_ja: str
    default_strategy: str

    @abstractmethod
    def decide(self, context: StrategyContext) -> StrategyDecision:
        pass
```

---

## 6.2 ユーティリティ関数

```python
def abs_gt(value: float | None, threshold: float) -> bool:
    return value is not None and abs(value) > threshold


def abs_le(value: float | None, threshold: float) -> bool:
    return value is not None and abs(value) <= threshold


def ge(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold
```

`None` の扱いは重要。

* 必須条件に使う値が `None` の場合は原則 `False`
* 安全側に倒すなら `skip`
* 欠損時に default 実行するか skip するかはルールごとに明記する

---

# 7. 実装対象ルール

## 7.1 Rule 406：固定運用の第1候補

### 日本語名

```text
GapOvht + 寄りgap制限 + 弱rotation除外 + SHORT過熱時LONG反転
```

### ロジック

```python
if abs(open_gap) > 0.015:
    skip

elif rotation_regime == "weak_rotation":
    skip

elif abs(short_gap) > 0.010:
    use long_flip_oc

else:
    use gap_ovht_oc
```

### 実装例

```python
class Rule406OpenGapRotShortFlip(StrategyRule):
    rule_id = "rule_406"
    rule_name_ja = "GapOvht + 寄りgap制限 + 弱rotation除外 + SHORT過熱時LONG反転"
    description_ja = (
        "普段はGapOvht除外OCを使う。"
        "ただし、寄り付きgapが1.5%を超える日、またはsector rotationが弱い日は見送る。"
        "SHORT側gapが1.0%を超える日は、寄り付きでSHORT側が過熱している可能性があるため、LONG反転OCへ切り替える。"
    )
    default_strategy = "gap_ovht_oc"

    def decide(self, context: StrategyContext) -> StrategyDecision:
        if not abs_le(context.open_gap, 0.015):
            return StrategyDecision(
                selected_strategy="skip",
                rule_id=self.rule_id,
                rule_name_ja=self.rule_name_ja,
                action="skip",
                reason_ja="寄りgapが1.5%を超える、または欠損のため見送り",
                default_strategy=self.default_strategy,
                matched_filter="abs_open_gap <= 1.5%",
            )

        if context.rotation_regime == "weak_rotation":
            return StrategyDecision(
                selected_strategy="skip",
                rule_id=self.rule_id,
                rule_name_ja=self.rule_name_ja,
                action="skip",
                reason_ja="rotation_regime が weak_rotation のため見送り",
                default_strategy=self.default_strategy,
                matched_filter="rotation_regime != weak_rotation",
            )

        if abs_gt(context.short_gap, 0.010):
            return StrategyDecision(
                selected_strategy="long_flip_oc",
                rule_id=self.rule_id,
                rule_name_ja=self.rule_name_ja,
                action="override",
                reason_ja="SHORT側gapが1.0%を超えたため、LONG反転OCへ切り替え",
                default_strategy=self.default_strategy,
                override_strategy="long_flip_oc",
                matched_override="abs_short_gap > 1.0%",
            )

        return StrategyDecision(
            selected_strategy="gap_ovht_oc",
            rule_id=self.rule_id,
            rule_name_ja=self.rule_name_ja,
            action="execute",
            reason_ja="フィルタ条件を満たし、切替条件に該当しないためGapOvht除外OCを実行",
            default_strategy=self.default_strategy,
        )
```

---

## 7.2 Rule 399：直近重視・低稼働高品質型

### 日本語名

```text
GapOvht + 強シグナル選別 + 高ボラgap時LONG反転
```

### ロジック

```python
if candidate_signal_strength < 0.3:
    skip

elif vol_regime == "high_vol" and abs(open_gap) > 0.005:
    use long_flip_oc

else:
    use gap_ovht_oc
```

### 意味

* 弱いシグナルの日は取引しない
* 高ボラかつ寄りgapが出た日は、日中リバーサルを警戒してLONG反転OCへ切り替える
* 稼働率は低いが、直近環境への適応候補

---

## 7.3 Rule 13：防御型

### 日本語名

```text
GapOvht + 高ボラ/強rotation限定 + SHORT過熱時SHORT単独
```

### ロジック

```python
if not (vol_regime == "high_vol" or rotation_regime == "strong_rotation"):
    skip

elif abs(short_gap) > 0.010:
    use short_only_oc

else:
    use gap_ovht_oc
```

### 意味

* 動きのある日だけ取引する
* SHORT側gapが大きい日は、LONG反転ではなくSHORT単独に切り替える
* 防御寄りのメタ戦略

---

## 7.4 Rule 87：LGap切替型

### 日本語名

```text
GapOvht + 高ボラ/強rotation限定 + SHORT過熱時LGap切替
```

### ロジック

```python
if not (vol_regime == "high_vol" or rotation_regime == "strong_rotation"):
    skip

elif abs(short_gap) > 0.0075:
    use lgap_oc

else:
    use gap_ovht_oc
```

### 意味

* 通常はGapOvht
* 動きのある日に限定
* SHORT側gapが過熱したら、LONG側gap除外を行うLGapへ逃がす
* 急落・流動性ショック対策として補助候補

---

## 7.5 Rule 1357：トレンド条件 + LGap切替型

### 日本語名

```text
GapOvht + 方向性相場限定 + 寄りgap過熱時LGap切替
```

### ロジック

```python
if trend_regime not in ("uptrend", "downtrend"):
    skip

elif abs(open_gap) > 0.0075:
    use lgap_oc

else:
    use gap_ovht_oc
```

### 意味

* 横ばい相場を避ける
* 上昇または下降の方向性がある日だけ取引
* 寄り付きgapが過熱した場合はLGapへ切り替える

---

## 7.6 Rolling3RuleSelector：年次ルール選択型

### 日本語名

```text
rolling3 年次メタルール選択
```

### ロジック

```text
毎年、直近3年の成績で上位ルールを選び、
翌年はそのルールを使う
```

### 実装方針

`Rolling3RuleSelector` は、直接売買判断をするルールではなく、**対象年に使うルールIDを返すセレクタ**として実装する。

```python
class RuleSelector(ABC):
    @abstractmethod
    def select_rule_id(self, target_date: date) -> str:
        pass
```

設定方法は2通り。

### 案A：事前計算テーブル方式

```text
year, selected_rule_id
2017, rule_406
2018, rule_406
2019, rule_1586
...
```

日次処理では、対象日の年から rule_id を引く。

メリット。

* 実装が簡単
* 本番運用で安定
* 監査しやすい

### 案B：毎年自動再計算方式

年初または指定タイミングで、直近3年のバックテストから rule_id を再選択する。

メリット。

* 将来運用に自然
* 継続学習型

デメリット。

* 実装が重い
* バックテスト基盤との依存が強い
* 再現性管理が必要

最初は **案A：事前計算テーブル方式** を推奨する。

---

# 8. ルールレジストリ

## 8.1 registry.py

```python
from app.strategies.base import StrategyRule
from app.strategies.meta.rule_406 import Rule406OpenGapRotShortFlip
from app.strategies.meta.rule_399 import Rule399StrongSignalHighVolFlip
from app.strategies.meta.rule_13 import Rule13HighVolRotationShortOnly
from app.strategies.meta.rule_87 import Rule87LGapSwitch
from app.strategies.meta.rule_1357 import Rule1357TrendLGapSwitch


_RULES: dict[str, StrategyRule] = {
    "rule_406": Rule406OpenGapRotShortFlip(),
    "rule_399": Rule399StrongSignalHighVolFlip(),
    "rule_13": Rule13HighVolRotationShortOnly(),
    "rule_87": Rule87LGapSwitch(),
    "rule_1357": Rule1357TrendLGapSwitch(),
}


def get_rule(rule_id: str) -> StrategyRule:
    try:
        return _RULES[rule_id]
    except KeyError:
        raise ValueError(f"Unknown strategy rule_id: {rule_id}")


def list_rules() -> list[StrategyRule]:
    return list(_RULES.values())
```

---

# 9. 設定でルールを切り替える

## 9.1 設定項目

DB または設定ファイルに以下を持たせる。

```text
active_strategy_rule_id
```

例。

```json
{
  "active_strategy_rule_id": "rule_406"
}
```

rolling3 を使う場合。

```json
{
  "active_strategy_rule_id": "rolling3_selector"
}
```

---

## 9.2 設定API

追加するAPI。

| Method | Path                           | 内容                   |
| ------ | ------------------------------ | -------------------- |
| GET    | `/strategy-rules`              | 利用可能なルール一覧           |
| GET    | `/strategy-rules/active`       | 現在有効なルール             |
| PUT    | `/strategy-rules/active`       | 有効ルールを変更             |
| POST   | `/strategy-rules/preview`      | 指定contextで判定結果をプレビュー |
| GET    | `/strategy-rules/descriptions` | 日本語説明一覧              |

---

## 9.3 レスポンス例

```json
{
  "rule_id": "rule_406",
  "rule_name_ja": "GapOvht + 寄りgap制限 + 弱rotation除外 + SHORT過熱時LONG反転",
  "default_strategy": "gap_ovht_oc",
  "description_ja": "普段はGapOvht除外OCを使う。ただし..."
}
```

---

# 10. 説明ページ

## 10.1 ページ名

```text
戦略ルール説明
```

## 10.2 URL例

```text
/settings/strategy-rules
/strategy-rules/help
```

## 10.3 表示内容

ページには以下を表示する。

| 表示項目  | 内容                    |
| ----- | --------------------- |
| ルールID | `rule_406` など         |
| ルール名  | 日本語名                  |
| 基本戦略  | 普段使う戦略                |
| 取引条件  | どんな日に取引するか            |
| 見送り条件 | どんな日は取引しないか           |
| 切替条件  | どんな条件で別戦略へ切り替えるか      |
| 切替先   | LONG反転、LGap、SHORT単独など |
| 狙い    | なぜそのルールがあるか           |
| 注意点   | 過学習、低稼働、ショック耐性など      |

---

# 11. 説明ページ用の日本語文言

## Rule 406

| 項目    | 内容                                                                             |
| ----- | ------------------------------------------------------------------------------ |
| ルールID | `rule_406`                                                                     |
| ルール名  | GapOvht + 寄りgap制限 + 弱rotation除外 + SHORT過熱時LONG反転                               |
| 基本戦略  | GapOvht除外OC                                                                    |
| 取引条件  | 寄りgap絶対値が1.5%以下、かつ rotation_regime が weak_rotation ではない                        |
| 見送り条件 | 寄りgapが1.5%を超える、または weak_rotation                                               |
| 切替条件  | SHORT側gap絶対値が1.0%超                                                             |
| 切替先   | LONG反転OC                                                                       |
| 狙い    | 寄り付きが過熱しすぎた日と、sector rotationが弱い日を避ける。SHORT側が寄りで過熱した日は日中リバーサルを警戒し、LONG反転へ切り替える |
| 注意点   | 固定ルール候補として最重要。ただし閾値は今後もwalk-forwardで検証する                                       |

---

## Rule 399

| 項目    | 内容                                         |
| ----- | ------------------------------------------ |
| ルールID | `rule_399`                                 |
| ルール名  | GapOvht + 強シグナル選別 + 高ボラgap時LONG反転          |
| 基本戦略  | GapOvht除外OC                                |
| 取引条件  | candidate_signal_strength が0.3以上           |
| 見送り条件 | candidate_signal_strength が0.3未満           |
| 切替条件  | high_vol かつ寄りgap絶対値が0.5%超                  |
| 切替先   | LONG反転OC                                   |
| 狙い    | シグナルが強い日だけ取引し、高ボラで寄りgapが出た日は通常方向ではなく反転側を使う |
| 注意点   | 稼働率は低め。直近適応型として扱う                          |

---

## Rule 13

| 項目    | 内容                                                 |
| ----- | -------------------------------------------------- |
| ルールID | `rule_13`                                          |
| ルール名  | GapOvht + 高ボラ/強rotation限定 + SHORT過熱時SHORT単独        |
| 基本戦略  | GapOvht除外OC                                        |
| 取引条件  | high_vol または strong_rotation                       |
| 見送り条件 | high_vol でも strong_rotation でもない                   |
| 切替条件  | SHORT側gap絶対値が1.0%超                                 |
| 切替先   | SHORT単独OC                                          |
| 狙い    | 動きのある日だけ取引する。SHORT側gapが大きい日は、LONG反転ではなくSHORT単独に寄せる |
| 注意点   | 防御型候補。稼働率はやや下がる                                    |

---

## Rule 87

| 項目    | 内容                                          |
| ----- | ------------------------------------------- |
| ルールID | `rule_87`                                   |
| ルール名  | GapOvht + 高ボラ/強rotation限定 + SHORT過熱時LGap切替  |
| 基本戦略  | GapOvht除外OC                                 |
| 取引条件  | high_vol または strong_rotation                |
| 見送り条件 | high_vol でも strong_rotation でもない            |
| 切替条件  | SHORT側gap絶対値が0.75%超                         |
| 切替先   | LGap除外OC                                    |
| 狙い    | 動きのある日だけGapOvhtを使い、SHORT側gapが過熱した日はLGapへ逃がす |
| 注意点   | 急落・流動性ショック対策として補助的に使う                       |

---

## Rule 1357

| 項目    | 内容                                             |
| ----- | ---------------------------------------------- |
| ルールID | `rule_1357`                                    |
| ルール名  | GapOvht + 方向性相場限定 + 寄りgap過熱時LGap切替             |
| 基本戦略  | GapOvht除外OC                                    |
| 取引条件  | uptrend または downtrend                          |
| 見送り条件 | sideways                                       |
| 切替条件  | 寄りgap絶対値が0.75%超                                |
| 切替先   | LGap除外OC                                       |
| 狙い    | 横ばい相場を避け、方向性のある相場だけ取引する。寄りgapが過熱した日はLGapに切り替える |
| 注意点   | 補助候補。単独本命ではない                                  |

---

## Rolling3

| 項目    | 内容                                     |
| ----- | -------------------------------------- |
| ルールID | `rolling3_selector`                    |
| ルール名  | rolling3 年次メタルール選択                     |
| 基本戦略  | 年ごとに異なる                                |
| 取引条件  | 選ばれた各ルールに従う                            |
| 見送り条件 | 選ばれた各ルールに従う                            |
| 切替条件  | 選ばれた各ルールに従う                            |
| 切替先   | 選ばれた各ルールに従う                            |
| 狙い    | 直近3年で良かったルールを翌年に使い、相場環境の変化に追随する        |
| 注意点   | 実運用では、年初時点で未来を見ずに選定する必要がある。選定履歴を必ず保存する |

---

# 12. 日次シグナルへの組み込み

既存の日次シグナル生成処理に以下を追加する。

```text
1. 日次シグナル候補を生成
2. regime / gap / signal_strength を計算
3. active_strategy_rule_id を取得
4. StrategyContext を作成
5. rule.decide(context) を実行
6. selected_strategy に従って採用候補を決定
7. decision情報をレスポンス・履歴に含める
```

APIレスポンスには以下を追加する。

```json
{
  "strategy_decision": {
    "rule_id": "rule_406",
    "rule_name_ja": "GapOvht + 寄りgap制限 + 弱rotation除外 + SHORT過熱時LONG反転",
    "selected_strategy": "long_flip_oc",
    "action": "override",
    "reason_ja": "SHORT側gapが1.0%を超えたため、LONG反転OCへ切り替え"
  }
}
```

---

# 13. 履歴DBへの保存

戦略履歴に以下の列を追加する。

| カラム                     | 型             | 内容                        |
| ----------------------- | ------------- | ------------------------- |
| `strategy_rule_id`      | TEXT          | 使用したルールID                 |
| `strategy_rule_name_ja` | TEXT          | 日本語ルール名                   |
| `selected_strategy`     | TEXT          | 実際に採用された戦略                |
| `strategy_action`       | TEXT          | execute / skip / override |
| `strategy_reason_ja`    | TEXT          | 判定理由                      |
| `default_strategy`      | TEXT          | 基本戦略                      |
| `override_strategy`     | TEXT nullable | 切替先                       |
| `matched_filter`        | TEXT nullable | 一致したフィルタ                  |
| `matched_override`      | TEXT nullable | 一致した切替条件                  |

既存DBに追加する場合は migration を用意する。

SQLiteなら例。

```sql
ALTER TABLE strategy_history ADD COLUMN strategy_rule_id TEXT;
ALTER TABLE strategy_history ADD COLUMN strategy_rule_name_ja TEXT;
ALTER TABLE strategy_history ADD COLUMN selected_strategy TEXT;
ALTER TABLE strategy_history ADD COLUMN strategy_action TEXT;
ALTER TABLE strategy_history ADD COLUMN strategy_reason_ja TEXT;
ALTER TABLE strategy_history ADD COLUMN default_strategy TEXT;
ALTER TABLE strategy_history ADD COLUMN override_strategy TEXT;
ALTER TABLE strategy_history ADD COLUMN matched_filter TEXT;
ALTER TABLE strategy_history ADD COLUMN matched_override TEXT;
```

---

# 14. UI要件

## 14.1 ルール設定画面

表示項目。

| UI項目         | 内容                  |
| ------------ | ------------------- |
| 現在の有効ルール     | rule_id、ルール名        |
| ルール選択ドロップダウン | 登録済みルール一覧           |
| ルール概要        | 選択中ルールの短い説明         |
| 保存ボタン        | 有効ルールを更新            |
| プレビューボタン     | 今日のcontextで判定結果を見る  |
| 注意表示         | rolling3 や CC参考枠の注意 |

---

## 14.2 日次シグナル画面

追加表示。

| 表示項目       | 内容                                       |
| ---------- | ---------------------------------------- |
| 採用ルール      | `rule_406` など                            |
| ルール名       | 日本語名                                     |
| 判定結果       | execute / skip / override                |
| 実行戦略       | GapOvht / LGap / LONG反転 / SHORT単独 / SKIP |
| 判定理由       | 日本語の説明                                   |
| default戦略  | 通常時の戦略                                   |
| override戦略 | 切替時の戦略                                   |

---

## 14.3 説明ページ

カード形式で表示する。

```text
[rule_406]
GapOvht + 寄りgap制限 + 弱rotation除外 + SHORT過熱時LONG反転

基本戦略:
  GapOvht除外OC

取引条件:
  寄りgap絶対値が1.5%以下
  rotation_regime が weak_rotation ではない

見送り条件:
  寄りgapが1.5%を超える
  weak_rotation

切替条件:
  SHORT側gap絶対値が1.0%超

切替先:
  LONG反転OC

狙い:
  ...
```

---

# 15. テスト方針

## 15.1 単体テスト

各ルールごとに `decide()` のテストを書く。

Rule406の例。

| ケース           | open_gap | rotation      | short_gap | 期待結果    |
| ------------- | -------: | ------------- | --------: | ------- |
| 通常実行          |    0.010 | mid_rotation  |     0.005 | GapOvht |
| 寄りgap過熱       |    0.020 | mid_rotation  |     0.005 | skip    |
| weak_rotation |    0.010 | weak_rotation |     0.005 | skip    |
| SHORT過熱       |    0.010 | mid_rotation  |     0.015 | LONG反転  |
| 欠損            |     None | mid_rotation  |     0.005 | skip    |

---

## 15.2 APIテスト

| API                            | テスト               |
| ------------------------------ | ----------------- |
| GET `/strategy-rules`          | 登録済みルールが返る        |
| GET `/strategy-rules/active`   | 現在の有効ルールが返る       |
| PUT `/strategy-rules/active`   | 有効ルールを変更できる       |
| PUT `/strategy-rules/active`   | 存在しないrule_idは400  |
| POST `/strategy-rules/preview` | 指定contextで判定結果が返る |

---

## 15.3 回帰テスト

以下を確認。

```text
- active_strategy_rule_id = rule_406 のとき、既存バックテスト結果と大きく乖離しない
- skip日の件数が想定通り
- override日の件数が想定通り
- selected_strategy の分布が想定通り
- 履歴DBに rule_id と reason_ja が保存される
```

---

# 16. 実装順序

```text
1. StrategyContext / StrategyDecision / StrategyRule を追加
2. primitive strategy id を整理
3. Rule406 / Rule399 / Rule13 / Rule87 / Rule1357 を実装
4. registry.py を実装
5. active_strategy_rule_id の設定保存を追加
6. strategy-rules API を追加
7. 日次シグナル生成に rule.decide() を組み込む
8. 履歴DBに decision 情報を保存
9. バックテストで active rule を使えるようにする
10. UIにルール設定画面を追加
11. UIに説明ページを追加
12. 単体テスト・APIテスト・回帰テストを追加
```

---

# 17. 受け入れ条件

以下を満たせば完了。

```text
- ルールを設定で切り替えられる
- ルール追加時に巨大な if/elif を増やさずに済む
- 各ルールが StrategyRule としてカプセル化されている
- 日次シグナルに rule_id / selected_strategy / reason_ja が表示される
- 履歴に採用ルールと判定理由が保存される
- 説明ページで各ルールの日本語説明を確認できる
- バックテストで任意ルールを指定できる
- Rule406 / Rule399 / Rule13 / Rule87 / Rule1357 が実装済み
- rolling3_selector は少なくとも事前計算テーブル方式で利用可能
- 現行CCは参考枠として扱い、実運用候補と混同しない
```
