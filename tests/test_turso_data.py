from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from juslag.turso_data import (
    ensure_data_schema, open_price_source, sync_artifacts, sync_prices,
    verify_artifacts, verify_prices,
)


class LocalSync:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.pushes = 0

    def execute(self, *args):
        return self.db.execute(*args)

    def executemany(self, *args):
        return self.db.executemany(*args)

    def commit(self):
        self.db.commit()

    def push(self):
        self.pushes += 1


def test_artifacts_change_only_and_verify(tmp_path: Path):
    conn = LocalSync()
    ensure_data_schema(conn)
    data = tmp_path / "data"
    data.mkdir()
    (data / "history.jsonl").write_bytes(b"one\n")
    assert sync_artifacts(conn, data) == 1
    assert sync_artifacts(conn, data) == 0
    assert conn.pushes == 1
    assert verify_artifacts(conn, data) == 1
    (data / "history.jsonl").write_bytes(b"two\n")
    with pytest.raises(ValueError, match="artifact mismatch"):
        verify_artifacts(conn, data)


def test_prices_backfill_retry_and_verify(tmp_path: Path):
    path = tmp_path / "prices.db"
    with sqlite3.connect(path) as source:
        source.execute("""CREATE TABLE prices (
            ticker TEXT, date TEXT, price_mode TEXT, open REAL, close REAL,
            PRIMARY KEY (ticker, date, price_mode))""")
        source.executemany("INSERT INTO prices VALUES (?, ?, ?, ?, ?)", [
            ("A", "2026-09-18", "raw", 1.0, 2.0),
            ("A", "2026-09-18", "adjusted", 1.5, 2.5),
        ])
    conn = LocalSync()
    ensure_data_schema(conn)
    source = open_price_source(path)
    try:
        assert sync_prices(conn, source, batch_size=1) == (2, 2)
        assert verify_prices(conn, source) == 2
        assert sync_prices(conn, source, batch_size=1) == (2, 0)
        assert conn.pushes == 1
        conn.execute("UPDATE juslag_prices SET close = 9 WHERE price_mode = 'raw'")
        with pytest.raises(ValueError, match="price mismatch"):
            verify_prices(conn, source)
        assert sync_prices(conn, source, batch_size=1) == (2, 1)
        assert verify_prices(conn, source) == 2
    finally:
        source.close()
