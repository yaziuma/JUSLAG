"""Copy Git artifacts and the price cache into Turso without deleting older rows."""
from __future__ import annotations

import hashlib
import math
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

PRICE_COLUMNS = ("ticker", "date", "price_mode", "open", "close")
PRICE_SELECT = "SELECT ticker, date, price_mode, open, close FROM prices ORDER BY ticker, date, price_mode"
def _write_price_batch(conn: Any, batch: list[tuple]) -> None:
    values = ", ".join(["(?, ?, ?, ?, ?)"] * len(batch))
    params = tuple(value for row in batch for value in row)
    conn.execute(
        "INSERT OR REPLACE INTO juslag_prices "
        "(ticker, date, price_mode, open, close) VALUES " + values,
        params,
    )
    conn.commit()


def ensure_data_schema(conn: Any) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS juslag_prices (
        ticker TEXT NOT NULL, date TEXT NOT NULL, price_mode TEXT NOT NULL,
        open REAL, close REAL, PRIMARY KEY (ticker, date, price_mode)
    )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS juslag_prices_mode_date
        ON juslag_prices(price_mode, date)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS juslag_prices_ticker_mode_date
        ON juslag_prices(ticker, price_mode, date)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS juslag_artifacts (
        path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, content BLOB NOT NULL
    )""")
    conn.commit()


def artifact_paths(data_dir: Path) -> list[Path]:
    if not data_dir.is_dir():
        raise ValueError("data directory is missing")
    return sorted(path for path in data_dir.rglob("*") if path.is_file())


def sync_artifacts(conn: Any, data_dir: Path) -> int:
    existing = dict(conn.execute("SELECT path, sha256 FROM juslag_artifacts").fetchall())
    changed = 0
    for path in artifact_paths(data_dir):
        relative = path.relative_to(data_dir).as_posix()
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if existing.get(relative) == digest:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO juslag_artifacts(path, sha256, content) VALUES (?, ?, ?)",
            (relative, digest, content),
        )
        changed += 1
    conn.commit()
    if changed:
        conn.push()
    return changed


def verify_artifacts(conn: Any, data_dir: Path) -> int:
    stored = dict(conn.execute("SELECT path, content FROM juslag_artifacts").fetchall())
    paths = artifact_paths(data_dir)
    for path in paths:
        relative = path.relative_to(data_dir).as_posix()
        if stored.get(relative) != path.read_bytes():
            raise ValueError(f"artifact mismatch: {relative}")
    return len(paths)


def open_price_source(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ValueError("price cache is missing")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    if conn.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        conn.close()
        raise ValueError("price cache integrity check failed")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(prices)")}
    if not set(PRICE_COLUMNS) <= columns:
        conn.close()
        raise ValueError("price cache schema is incompatible")
    return conn


def _remote_prices(conn: Any) -> dict[tuple[str, str, str], tuple[float | None, float | None]]:
    return {
        (ticker, date, mode): (open_price, close_price)
        for ticker, date, mode, open_price, close_price in conn.execute(
            "SELECT ticker, date, price_mode, open, close FROM juslag_prices"
        ).fetchall()
    }


def _price_values_equal(
    left: tuple[float | None, float | None] | None,
    right: tuple[float | None, float | None],
) -> bool:
    if left is None:
        return False
    return all(
        a == b if a is None or b is None else math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-8)
        for a, b in zip(left, right)
    )


def compare_price_caches(
    left: sqlite3.Connection, right: sqlite3.Connection,
) -> tuple[int, int, Counter, Counter]:
    previous = {row[:3]: row[3:] for row in left.execute(PRICE_SELECT)}
    by_mode_year: Counter = Counter()
    by_ticker_mode: Counter = Counter()
    right_count = 0
    for ticker, date, mode, open_price, close_price in right.execute(PRICE_SELECT):
        right_count += 1
        if _price_values_equal(previous.get((ticker, date, mode)), (open_price, close_price)):
            continue
        by_mode_year[(mode, date[:4])] += 1
        by_ticker_mode[(ticker, mode)] += 1
    return len(previous), right_count, by_mode_year, by_ticker_mode


def sync_prices(conn: Any, source: sqlite3.Connection, *, batch_size: int = 1000) -> tuple[int, int]:
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    if source.execute("SELECT count(*) FROM prices").fetchone()[0] == 0:
        raise ValueError("price cache is empty")
    existing = _remote_prices(conn)
    changed = 0
    total = 0
    since_push = 0
    batch: list[tuple] = []
    for row in source.execute(PRICE_SELECT):
        total += 1
        key = row[:3]
        if _price_values_equal(existing.get(key), row[3:]):
            continue
        batch.append(row)
        if len(batch) == batch_size:
            _write_price_batch(conn, batch)
            changed += len(batch)
            since_push += len(batch)
            batch.clear()
            if since_push >= 10000:
                conn.push()
                since_push = 0
    if batch:
        _write_price_batch(conn, batch)
        changed += len(batch)
        since_push += len(batch)
    if since_push:
        conn.push()
    return total, changed


def verify_prices(conn: Any, source: sqlite3.Connection) -> int:
    stored = _remote_prices(conn)
    total = 0
    for row in source.execute(PRICE_SELECT):
        total += 1
        if not _price_values_equal(stored.get(row[:3]), row[3:]):
            raise ValueError(
                f"price mismatch: {row[0]} {row[1]} {row[2]} "
                f"source={row[3:]!r} cloud={stored.get(row[:3])!r}"
            )
    return total
