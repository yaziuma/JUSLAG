from __future__ import annotations

RULE_DESCRIPTIONS_JA: dict[str, dict[str, str]] = {
    "rule_406": {
        "rule_id": "rule_406",
        "rule_name": "GapOvht + 寄りgap制限 + 弱rotation除外 + SHORT過熱時LONG反転",
        "base_strategy": "GapOvht除外OC",
        "trade_condition": "寄りgap絶対値が1.5%以下、かつ rotation_regime が weak_rotation ではない",
        "skip_condition": "寄りgapが1.5%を超える、または weak_rotation",
        "switch_condition": "SHORT側gap絶対値が1.0%超",
        "switch_target": "LONG反転OC",
        "purpose": (
            "寄り付きが過熱しすぎた日と、sector rotationが弱い日を避ける。"
            "SHORT側が寄りで過熱した日は日中リバーサルを警戒し、LONG反転へ切り替える。"
        ),
        "caution": "固定ルール候補として最重要。ただし閾値は今後もwalk-forwardで検証する。",
    },
    "rule_406_no_flip": {
        "rule_id": "rule_406_no_flip",
        "rule_name": "GapOvht + 寄りgap制限 + 弱rotation除外（LONG反転なし）",
        "base_strategy": "GapOvht除外OC",
        "trade_condition": "寄りgap絶対値が1.5%以下、かつ rotation_regime が weak_rotation ではない",
        "skip_condition": "寄りgapが1.5%を超える、または weak_rotation",
        "switch_condition": "なし（SHORT過熱時の LONG反転を行わない）",
        "switch_target": "なし",
        "purpose": (
            "rule_406 から LONG反転ロジックを除いたアブレーションバリアント。"
            "skip フィルタの効果だけを分離して検証するために使用する。"
        ),
        "caution": "rule_406 との比較専用。long_flip の有無が損益に与える影響を評価する。",
    },
    "rule_399": {
        "rule_id": "rule_399",
        "rule_name": "GapOvht + 強シグナル選別 + 高ボラgap時LONG反転",
        "base_strategy": "GapOvht除外OC",
        "trade_condition": "candidate_signal_strength が0.3以上",
        "skip_condition": "candidate_signal_strength が0.3未満",
        "switch_condition": "high_vol かつ寄りgap絶対値が0.5%超",
        "switch_target": "LONG反転OC",
        "purpose": (
            "シグナルが強い日だけ取引し、高ボラで寄りgapが出た日は通常方向ではなく反転側を使う。"
        ),
        "caution": "稼働率は低め。直近適応型として扱う。",
    },
    "rule_13": {
        "rule_id": "rule_13",
        "rule_name": "GapOvht + 高ボラ/強rotation限定 + SHORT過熱時SHORT単独",
        "base_strategy": "GapOvht除外OC",
        "trade_condition": "high_vol または strong_rotation",
        "skip_condition": "high_vol でも strong_rotation でもない",
        "switch_condition": "SHORT側gap絶対値が1.0%超",
        "switch_target": "SHORT単独OC",
        "purpose": (
            "動きのある日だけ取引する。SHORT側gapが大きい日は、LONG反転ではなくSHORT単独に寄せる。"
        ),
        "caution": "防御型候補。稼働率はやや下がる。",
    },
    "rule_87": {
        "rule_id": "rule_87",
        "rule_name": "GapOvht + 高ボラ/強rotation限定 + SHORT過熱時LGap切替",
        "base_strategy": "GapOvht除外OC",
        "trade_condition": "high_vol または strong_rotation",
        "skip_condition": "high_vol でも strong_rotation でもない",
        "switch_condition": "SHORT側gap絶対値が0.75%超",
        "switch_target": "LGap除外OC",
        "purpose": (
            "動きのある日だけGapOvhtを使い、SHORT側gapが過熱した日はLGapへ逃がす。"
        ),
        "caution": "急落・流動性ショック対策として補助的に使う。",
    },
    "rule_1357": {
        "rule_id": "rule_1357",
        "rule_name": "GapOvht + 方向性相場限定 + 寄りgap過熱時LGap切替",
        "base_strategy": "GapOvht除外OC",
        "trade_condition": "uptrend または downtrend",
        "skip_condition": "sideways",
        "switch_condition": "寄りgap絶対値が0.75%超",
        "switch_target": "LGap除外OC",
        "purpose": (
            "横ばい相場を避け、方向性のある相場だけ取引する。寄りgapが過熱した日はLGapに切り替える。"
        ),
        "caution": "補助候補。単独本命ではない。",
    },
    "rolling3_selector": {
        "rule_id": "rolling3_selector",
        "rule_name": "rolling3 年次メタルール選択",
        "base_strategy": "年ごとに異なる",
        "trade_condition": "選ばれた各ルールに従う",
        "skip_condition": "選ばれた各ルールに従う",
        "switch_condition": "選ばれた各ルールに従う",
        "switch_target": "選ばれた各ルールに従う",
        "purpose": (
            "直近3年で良かったルールを翌年に使い、相場環境の変化に追随する。"
        ),
        "fallback_rule": "rule_406（年次テーブル未設定時）",
        "caution": (
            "実運用では、年初時点で未来を見ずに選定する必要がある。選定履歴を必ず保存する。"
            "年次テーブル未設定の年は rule_406 にフォールバックする。"
        ),
    },
}
