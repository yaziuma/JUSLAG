#!/usr/bin/env python3
"""data/ 配下の日次運用結果から閲覧用静的サイトを生成する。

実行例:
    uv run python scripts/ops/render_pages.py --out _site
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from juslag.services.site import load_history, load_reports, render_site


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("_site"))
    args = parser.parse_args()

    history = load_history(args.data_dir / "history.jsonl")
    reports = load_reports(args.data_dir / "reports")
    capital_path = args.data_dir / "manual_strategy" / "capital_simulation.json"
    capital_simulation = (
        json.loads(capital_path.read_text(encoding="utf-8"))
        if capital_path.is_file()
        else None
    )
    preflights = sorted((args.data_dir / "manual_strategy" / "preflight").glob("*.json"))
    operational = None
    if preflights:
        preflight = json.loads(preflights[-1].read_text(encoding="utf-8"))
        as_of = preflight.get("as_of")
        def load_optional(path: Path):
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        operational = {
            "preflight": preflight,
            "order": load_optional(args.data_dir / "manual_strategy" / "orders" / f"{as_of}-entry.json"),
            "signal": load_optional(args.data_dir / "manual_strategy" / "signals" / f"{as_of}.json"),
            "intent": load_optional(args.data_dir / "manual_strategy" / "intents" / f"{as_of}-intent.json"),
            "rendered_at": datetime.now().astimezone().isoformat(),
        }
    render_site(
        history, reports, args.out,
        capital_simulation=capital_simulation,
        operational=operational,
    )
    print(f"rendered {len(reports)} report(s) -> {args.out}")


if __name__ == "__main__":
    main()
