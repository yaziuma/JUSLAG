from __future__ import annotations

import pandas as pd


def print_performance_table(perf_df: pd.DataFrame, eval_start: str, sample_end: str | None) -> None:
    print("=" * 60)
    print(f"パフォーマンス比較 (評価期間: {eval_start}–{sample_end})")
    print("=" * 60)
    print(perf_df.to_string())


def print_signal_summary(signal_df: pd.DataFrame, reference_date: pd.Timestamp) -> None:
    print("=" * 70)
    print("本日の投資シグナル (明日の日本市場向け)")
    print("=" * 70)
    if pd.isna(reference_date):
        print("基準日 (米国市場終値): N/A")
    else:
        print(f"基準日 (米国市場終値): {reference_date.date()}")

    position_counts = signal_df["position"].value_counts().reindex(["LONG", "SHORT", "neutral"], fill_value=0)
    print(
        "ポジション件数 "
        f"LONG={position_counts['LONG']} / SHORT={position_counts['SHORT']} / neutral={position_counts['neutral']}"
    )

    top3 = signal_df.nlargest(3, "signal")[["sector", "signal", "position"]]
    bottom3 = signal_df.nsmallest(3, "signal")[["sector", "signal", "position"]]
    print("\n上位3件")
    print(top3.to_string())
    print("\n下位3件")
    print(bottom3.to_string())
