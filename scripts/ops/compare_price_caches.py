"""Compare two Actions price caches without reading or writing Turso Cloud."""

from __future__ import annotations

import argparse
from contextlib import closing
from pathlib import Path

from juslag.turso_data import compare_price_caches, open_price_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--right", type=Path, required=True)
    args = parser.parse_args()
    with closing(open_price_source(args.left)) as left, closing(open_price_source(args.right)) as right:
        left_count, right_count, by_mode_year, by_ticker_mode = compare_price_caches(left, right)
    print(f"Price cache rows: left={left_count} right={right_count} changed={sum(by_mode_year.values())}")
    for (mode, year), count in sorted(by_mode_year.items()):
        print(f"  {mode} {year}: {count}")
    for (ticker, mode), count in by_ticker_mode.most_common():
        print(f"  {ticker} {mode}: {count}")


if __name__ == "__main__":
    main()
