"""Probe Cloud Sync write/read with a unique disposable table; never print credentials."""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import turso.sync


def main() -> None:
    url = os.environ["JUSLAG_TURSO_DATABASE_URL"]
    token = os.environ["JUSLAG_TURSO_AUTH_TOKEN"]
    if not url.startswith(("libsql://", "turso://")):
        raise SystemExit("Unsupported Cloud URL scheme")
    table = "juslag_sync_probe_" + uuid.uuid4().hex
    created = False
    with tempfile.TemporaryDirectory(prefix="juslag-cloud-sync-probe-") as root:
        path = Path(root)
        try:
            writer = turso.sync.connect(
                path=str(path / "writer.db"), remote_url=url,
                auth_token=token, bootstrap_if_empty=False,
            )
            writer.pull()
            writer.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            writer.execute(f"INSERT INTO {table} VALUES (?, ?)", ("probe", '{"ok":true}'))
            writer.commit()
            created = True
            writer.push()

            reader = turso.sync.connect(
                path=str(path / "reader.db"), remote_url=url,
                auth_token=token, bootstrap_if_empty=False,
            )
            reader.pull()
            assert reader.execute(f"SELECT payload FROM {table} WHERE id = ?", ("probe",)).fetchone() == (
                '{"ok":true}',
            )
            print("PASS: Cloud push and independent-client pull/read")
        except Exception as exc:
            print(f"FAIL: {type(exc).__name__}; probe_table={table}; remote residue possible")
            raise SystemExit(1) from None
        finally:
            if created:
                try:
                    writer.execute(f"DROP TABLE {table}")
                    writer.commit()
                    writer.push()
                    verifier = turso.sync.connect(
                        path=str(path / "verifier.db"), remote_url=url,
                        auth_token=token, bootstrap_if_empty=False,
                    )
                    verifier.pull()
                    count = verifier.execute(
                        "SELECT count(*) FROM sqlite_master WHERE type = ? AND name = ?",
                        ("table", table),
                    ).fetchone()[0]
                    if count != 0:
                        raise RuntimeError("probe table remains after cleanup")
                    print("PASS: probe table absent after independent pull")
                except Exception as exc:
                    print(f"CLEANUP FAILED: {type(exc).__name__}; probe_table={table}")
                    raise SystemExit(2) from None


if __name__ == "__main__":
    main()
