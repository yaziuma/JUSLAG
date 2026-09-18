"""Sync the exact daily price cache and Git data directory to Turso."""
from __future__ import annotations

import argparse
import tempfile
from contextlib import closing
from pathlib import Path

from juslag.turso_data import (
    ensure_data_schema, open_price_source, sync_artifacts, sync_prices,
    verify_artifacts, verify_prices,
)
from turso_daily import connect


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", type=Path)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="juslag-turso-data-") as directory:
            root = Path(directory)
            writer = connect(root / "writer.db")
            ensure_data_schema(writer)
            writer.push()
            artifact_changes = sync_artifacts(writer, args.data)
            if args.prices is None:
                reader = connect(root / "reader.db")
                artifact_total = verify_artifacts(reader, args.data)
                print(f"PASS: artifacts={artifact_total} changed={artifact_changes}")
                return
            with closing(open_price_source(args.prices)) as source:
                price_total, price_changes = sync_prices(
                    writer, source, batch_size=args.batch_size,
                )
                reader = connect(root / "reader.db")
                artifact_total = verify_artifacts(reader, args.data)
                if verify_prices(reader, source) != price_total:
                    raise ValueError("price row count mismatch")
                print(
                    f"PASS: artifacts={artifact_total} changed={artifact_changes} "
                    f"prices={price_total} changed={price_changes}"
                )
    except Exception as exc:  # noqa: BLE001 - SDK errors may contain credentials
        raise SystemExit(f"Turso data sync failed: {type(exc).__name__}") from None


if __name__ == "__main__":
    main()
