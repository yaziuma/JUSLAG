"""Measure opening-price drift to the first observed post-open 5-minute bar."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from juslag.intraday import load_intraday_bars


def analyze_bars(bars: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    bars = bars.copy()
    bars["jst"] = pd.to_datetime(bars["bar_start_utc"], utc=True).dt.tz_convert("Asia/Tokyo")
    bars["day"] = bars["jst"].dt.date
    bars["clock"] = bars["jst"].dt.strftime("%H:%M")
    rows = []
    for (ticker, day), group in bars.groupby(["ticker", "day"]):
        opening = group[group["clock"] == "09:00"]
        later = group[(group["clock"] >= "09:10") & (group["clock"] <= "09:30")].sort_values("jst")
        if opening.empty or later.empty:
            rows.append({"ticker": ticker, "day": str(day), "status": "missing_open_or_postopen"})
            continue
        open_price = float(opening.iloc[0]["open"])
        delayed = float(later.iloc[0]["open"])
        rows.append({
            "ticker": ticker,
            "day": str(day),
            "status": "observed_proxy",
            "entry_bar_jst": later.iloc[0]["jst"].isoformat(),
            "first_observed_jst": pd.Timestamp(later.iloc[0]["observed_at_utc"]).tz_convert("Asia/Tokyo").isoformat()
            if "observed_at_utc" in later else "",
            "observation_delay_minutes": round(
                (pd.Timestamp(later.iloc[0]["observed_at_utc"]) - pd.Timestamp(later.iloc[0]["bar_start_utc"]))
                .total_seconds() / 60, 2,
            ) if "observed_at_utc" in later else None,
            "opening_price": open_price,
            "postopen_bar_open": delayed,
            "signed_drift_bps": (delayed / open_price - 1) * 10_000,
            "absolute_drift_bps": abs(delayed / open_price - 1) * 10_000,
        })
    detail = pd.DataFrame(rows)
    valid = detail[detail["status"] == "observed_proxy"]
    summary = {
        "ticker_days": len(detail),
        "observed_proxy": len(valid),
        "missing_open_or_postopen": len(detail) - len(valid),
        "median_abs_drift_bps": round(float(valid["absolute_drift_bps"].median()), 2) if not valid.empty else None,
        "p90_abs_drift_bps": round(float(valid["absolute_drift_bps"].quantile(0.9)), 2) if not valid.empty else None,
        "max_abs_drift_bps": round(float(valid["absolute_drift_bps"].max()), 2) if not valid.empty else None,
        "median_observation_delay_minutes": round(float(valid["observation_delay_minutes"].median()), 2)
        if "observation_delay_minutes" in valid and valid["observation_delay_minutes"].notna().any() else None,
    }
    return detail, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/intraday/prices.sqlite"))
    parser.add_argument("--snapshot-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("/tmp/juslag_postopen_intraday.csv"))
    args = parser.parse_args()
    bars = load_intraday_bars(snapshot_dir=args.snapshot_dir) if args.snapshot_dir else load_intraday_bars(db=args.db)
    if bars.empty:
        raise SystemExit("No captured 5-minute bars")
    detail, summary = analyze_bars(bars)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    detail.to_csv(args.out, index=False)
    print(f"{summary} out={args.out}")


if __name__ == "__main__":
    main()
