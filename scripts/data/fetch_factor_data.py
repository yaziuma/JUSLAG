"""
Kenneth French Data Library から日本の FF3 + WML（日次）を取得し
data/external/factors/ に正規化 CSV を保存する。

使い方:
    uv run --with requests,pandas scripts/fetch_factor_data.py

保存先:
    data/external/factors/normalized/ff3_japan_daily.csv
    data/external/factors/normalized/carhart4_japan_daily.csv
    data/external/factors/normalized/ff3_metadata.json
"""
# /// script
# requires-python = ">=3.12"
# dependencies = ["requests", "pandas"]
# ///

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

FF3_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Japan_3_Factors_Daily_CSV.zip"
WML_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Japan_Mom_Factor_Daily_CSV.zip"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "data" / "external" / "factors" / "normalized"


def _download_zip(url: str) -> bytes:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


def parse_french_csv(content: bytes) -> pd.DataFrame:
    text = content.decode("latin-1")
    lines = text.splitlines()

    header_idx: int | None = None
    data_start: int | None = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith(",") and header_idx is None:
            header_idx = i
        if s and s[0].isdigit() and data_start is None:
            data_start = i
            break

    if data_start is None:
        raise ValueError("データ行が見つかりません")

    data_lines: list[str] = []
    for line in lines[data_start:]:
        s = line.strip()
        if not s or not s[0].isdigit():
            break
        data_lines.append(s)

    col_line = lines[header_idx].strip() if header_idx is not None else ""
    col_names = ["date"] + [c.strip() for c in col_line.split(",") if c.strip()]

    df = pd.read_csv(
        io.StringIO("\n".join(data_lines)),
        header=None,
        names=col_names,
        sep=r"\s*,\s*",
        engine="python",
    )
    df["date"] = pd.to_datetime(df["date"].astype(str).str.strip(), format="%Y%m%d")
    df = df.set_index("date")
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.replace(-99.99, float("nan"))
    df = df / 100.0
    return df


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== Kenneth French Japan Factor Data 取得 ===")

    # FF3
    print(f"  FF3 ダウンロード中... {FF3_URL}")
    ff3_zip = _download_zip(FF3_URL)
    with zipfile.ZipFile(io.BytesIO(ff3_zip)) as z:
        csv_name = next(n for n in z.namelist() if n.endswith(".CSV") or n.endswith(".csv"))
        ff3_raw = z.read(csv_name)
    ff3 = parse_french_csv(ff3_raw)
    ff3.columns = [c.strip().lower().replace("-", "_").replace(" ", "_") for c in ff3.columns]
    print(f"  FF3: {len(ff3)} 行  {ff3.index.min().date()} – {ff3.index.max().date()}")
    print(f"  列: {list(ff3.columns)}")

    # WML (Momentum)
    print(f"  WML ダウンロード中... {WML_URL}")
    wml_zip = _download_zip(WML_URL)
    with zipfile.ZipFile(io.BytesIO(wml_zip)) as z:
        csv_name = next(n for n in z.namelist() if n.endswith(".CSV") or n.endswith(".csv"))
        wml_raw = z.read(csv_name)
    wml = parse_french_csv(wml_raw)
    wml.columns = [c.strip().lower().replace("-", "_").replace(" ", "_") for c in wml.columns]
    # WML列名を統一
    wml = wml.rename(columns={wml.columns[0]: "wml"})
    print(f"  WML: {len(wml)} 行  {wml.index.min().date()} – {wml.index.max().date()}")

    # 保存: FF3
    ff3_path = OUT_DIR / "ff3_japan_daily.csv"
    ff3.to_csv(ff3_path)
    print(f"  → {ff3_path}")

    # 保存: Carhart4 = FF3 + WML（inner join）
    c4 = ff3.join(wml[["wml"]], how="inner")
    c4_path = OUT_DIR / "carhart4_japan_daily.csv"
    c4.to_csv(c4_path)
    print(f"  → {c4_path}  ({len(c4)} 行)")

    # メタデータ
    meta = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Kenneth French Data Library",
        "ff3_url": FF3_URL,
        "wml_url": WML_URL,
        "ff3_rows": int(len(ff3)),
        "ff3_start": str(ff3.index.min().date()),
        "ff3_end": str(ff3.index.max().date()),
        "carhart4_rows": int(len(c4)),
        "carhart4_start": str(c4.index.min().date()),
        "carhart4_end": str(c4.index.max().date()),
        "columns_ff3": list(ff3.columns),
        "columns_carhart4": list(c4.columns),
    }
    (OUT_DIR / "ff3_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print("=== 完了 ===")


if __name__ == "__main__":
    main()
