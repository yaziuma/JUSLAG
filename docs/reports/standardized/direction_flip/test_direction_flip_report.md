# 方向反転検証レポート

## 条件メタ情報

- 生成日時: `2026-06-09 02:00:39`
- 使用テンプレート: `direction_flip`
- 実行バージョン: `webui-standardized-v1`
- 対象期間: `2025-01-01` 〜 `2025-12-31`

## 条件サマリ

- `fill_policy`: `strict`
- `from_date`: `2025-01-01`
- `max_short_signal_from`: `-0.1`
- `max_short_signal_to`: `-0.1`
- `min_long_signal_from`: `0.1`
- `min_long_signal_to`: `0.1`
- `min_signal_spread_from`: `0.05`
- `min_signal_spread_to`: `0.05`
- `price_mode`: `raw`
- `quantile_q_from`: `0.3`
- `quantile_q_to`: `0.3`
- `rotation_regimes`: `['weak_rotation', 'mid_rotation', 'strong_rotation']`
- `to_date`: `2025-12-31`
- `trend_regimes`: `['uptrend', 'sideways', 'downtrend']`
- `vol_regimes`: `['low_vol', 'mid_vol', 'high_vol']`
- `window_l_from`: `60`
- `window_l_to`: `60`

## 分析結果サマリ

現行方向 vs 反転方向を比較し、期間分割・累積・MDD・勝率をサマリ化します。

## 所見

- 本実装は初期版（範囲UI + 固定値確定型）です。
- `*_from` と `*_to` は将来のグリッド展開に拡張可能です。
