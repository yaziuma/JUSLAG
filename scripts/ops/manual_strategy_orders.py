"""Generate or update the fixed manual five-session strategy ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from juslag.manual_strategy import (
    build_order_sheet,
    initial_state,
    latest_prices,
    load_manual_config,
    record_entry,
    record_exit,
)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "plan", "record-entry", "record-exit"))
    parser.add_argument("--config", type=Path, default=Path("config/manual_strategy.yaml"))
    parser.add_argument("--state", type=Path, default=Path("data/manual_strategy/state.json"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--prices", type=Path)
    parser.add_argument("--as-of")
    parser.add_argument("--sheet", type=Path)
    parser.add_argument("--fills", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = load_manual_config(args.config)
    if args.command == "init":
        if args.state.exists():
            raise SystemExit("state already exists")
        _write(args.state, initial_state(config))
        print(args.state)
        return
    state = _read(args.state)
    if args.command == "plan":
        if not all((args.report, args.prices, args.as_of, args.output)):
            parser.error("plan requires --report --prices --as-of --output")
        report = _read(args.report)
        prices = latest_prices(args.prices, args.as_of)
        sheet = build_order_sheet(report, state, config, prices, args.as_of)
        _write(args.output, sheet)
        print(args.output)
        return
    if not args.fills:
        parser.error("record commands require --fills")
    if args.command == "record-entry" and not args.sheet:
        parser.error("record-entry requires --sheet")
    fills = json.loads(args.fills.read_text(encoding="utf-8"))
    updated = (
        record_entry(state, _read(args.sheet), fills)
        if args.command == "record-entry"
        else record_exit(state, fills)
    )
    _write(args.state, updated)
    print(args.state)


if __name__ == "__main__":
    main()
