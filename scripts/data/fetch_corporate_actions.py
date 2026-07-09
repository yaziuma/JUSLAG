"""
yfinance から米国・日本 ETF 全銘柄の dividends / splits を取得し
data/external/actions/ に正規化 CSV を保存する。

使い方:
    uv run --with yfinance,pandas scripts/fetch_corporate_actions.py

保存先:
    data/external/actions/raw/          ← 銘柄ごとの生 CSV
    data/external/actions/normalized/   ← actions_all.csv, dividends_all.csv, splits_all.csv
"""
# /// script
# requires-python = ">=3.12"
# dependencies = ["yfinance", "pandas"]
# ///

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

US_TICKERS = [
    "XLB", "XLE", "XLF", "XLI", "XLK",
    "XLP", "XLRE", "XLU", "XLV", "XLY", "XLC",
]

JP_TICKERS = [
    "1617.T", "1618.T", "1619.T", "1620.T", "1621.T",
    "1622.T", "1623.T", "1624.T", "1625.T", "1626.T",
    "1627.T", "1628.T", "1629.T", "1630.T", "1631.T",
    "1632.T", "1633.T",
]

ALL_TICKERS = US_TICKERS + JP_TICKERS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "external" / "actions"
RAW_DIR = DATA_DIR / "raw"
NORM_DIR = DATA_DIR / "normalized"


def fetch_yf_actions(ticker: str) -> pd.DataFrame:
    t = yf.Ticker(ticker)
    actions = t.actions

    rows: list[dict] = []
    if actions is not None and not actions.empty:
        for dt, row in actions.iterrows():
            date_str = str(dt.date()) if hasattr(dt, "date") else str(dt)[:10]
            div = float(row.get("Dividends", 0.0) or 0.0)
            spl = float(row.get("Stock Splits", 0.0) or 0.0)
            if div > 0:
                rows.append({"ticker": ticker, "date": date_str,
                              "action_type": "dividend", "value": div, "source": "yfinance"})
            if spl > 0:
                rows.append({"ticker": ticker, "date": date_str,
                              "action_type": "split", "value": spl, "source": "yfinance"})

    return pd.DataFrame(rows, columns=["ticker", "date", "action_type", "value", "source"])


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    NORM_DIR.mkdir(parents=True, exist_ok=True)

    print(f"=== Corporate Actions 取得 (US {len(US_TICKERS)} + JP {len(JP_TICKERS)} = {len(ALL_TICKERS)} 銘柄) ===")

    all_dfs: list[pd.DataFrame] = []
    errors: list[str] = []

    for ticker in ALL_TICKERS:
        print(f"  {ticker:10s} ...", end=" ", flush=True)
        try:
            df = fetch_yf_actions(ticker)
            raw_path = RAW_DIR / f"actions_{ticker.replace('.', '_')}.csv"
            df.to_csv(raw_path, index=False)
            all_dfs.append(df)
            divs = len(df[df["action_type"] == "dividend"])
            spls = len(df[df["action_type"] == "split"])
            print(f"dividend {divs:3d}件  split {spls:2d}件")
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append(f"{ticker}: {e}")
        time.sleep(0.3)

    combined = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame(
        columns=["ticker", "date", "action_type", "value", "source"])
    combined = combined.sort_values(["ticker", "date"]).reset_index(drop=True)

    combined.to_csv(NORM_DIR / "actions_all.csv", index=False)
    dividends = combined[combined["action_type"] == "dividend"].copy()
    dividends.to_csv(NORM_DIR / "dividends_all.csv", index=False)
    splits = combined[combined["action_type"] == "split"].copy()
    splits.to_csv(NORM_DIR / "splits_all.csv", index=False)

    meta = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
        "tickers_us": US_TICKERS,
        "tickers_jp": JP_TICKERS,
        "total_actions": int(len(combined)),
        "dividends": int(len(dividends)),
        "splits": int(len(splits)),
        "errors": errors,
    }
    (NORM_DIR / "actions_metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2))

    print()
    print(f"  統合ファイル: {NORM_DIR / 'actions_all.csv'}  ({len(combined):,} 件)")
    print(f"  Dividends  : {len(dividends):,} 件")
    print(f"  Splits     : {len(splits):,} 件")
    if errors:
        print(f"  エラー      : {len(errors)} 件 → {errors}")
    print("=== 完了 ===")


if __name__ == "__main__":
    main()
