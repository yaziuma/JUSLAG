from __future__ import annotations

import sqlite3
from pathlib import Path

from juslag.turso_data import compare_price_caches, open_price_source


def _price_db(path: Path, rows: list[tuple]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE prices (
            ticker TEXT, date TEXT, price_mode TEXT, open REAL, close REAL,
            PRIMARY KEY (ticker, date, price_mode))""")
        conn.executemany("INSERT INTO prices VALUES (?, ?, ?, ?, ?)", rows)


def test_compare_groups_only_changed_prices(tmp_path: Path):
    left = tmp_path / "left.db"
    right = tmp_path / "right.db"
    _price_db(left, [
        ("A", "2025-01-02", "raw", 1.0, 2.0),
        ("A", "2026-01-02", "adjusted", 1.0, 2.0),
    ])
    _price_db(right, [
        ("A", "2025-01-02", "raw", 1.0, 3.0),
        ("A", "2026-01-02", "adjusted", 1.0, 2.0),
        ("B", "2026-01-02", "raw", 4.0, 5.0),
    ])

    with open_price_source(left) as left_db, open_price_source(right) as right_db:
        left_count, right_count, by_year, by_ticker = compare_price_caches(left_db, right_db)
    assert (left_count, right_count) == (2, 3)
    assert by_year == {("raw", "2025"): 1, ("raw", "2026"): 1}
    assert by_ticker == {("A", "raw"): 1, ("B", "raw"): 1}
