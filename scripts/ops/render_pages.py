#!/usr/bin/env python3
"""data/ 配下の日次リサーチ結果から閲覧用静的サイトを生成する。

実行例:
    uv run python scripts/ops/render_pages.py --out _site
"""
from __future__ import annotations

import argparse
from pathlib import Path

from juslag.services.site import load_history, load_reports, render_site


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("_site"))
    args = parser.parse_args()

    history = load_history(args.data_dir / "history.jsonl")
    reports = load_reports(args.data_dir / "reports")
    render_site(history, reports, args.out)
    print(f"rendered {len(reports)} report(s) -> {args.out}")


if __name__ == "__main__":
    main()
