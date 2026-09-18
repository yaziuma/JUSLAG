"""Exercise Turso Sync against a disposable local sync server."""

import argparse
import tempfile
from pathlib import Path

import turso.sync


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18080")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="juslag-turso-poc-") as directory:
        root = Path(directory)
        writer = turso.sync.connect(path=str(root / "writer.db"), remote_url=args.url)
        reader = turso.sync.connect(path=str(root / "reader.db"), remote_url=args.url)

        writer.execute("CREATE TABLE poc (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        writer.commit()
        writer.execute("INSERT INTO poc VALUES (?, ?)", ("run-1", '{"ok":true}'))
        writer.commit()
        writer.push()
        reader.pull()
        assert reader.execute("SELECT payload FROM poc WHERE id = ?", ("run-1",)).fetchone() == ('{"ok":true}',)

        writer.execute("INSERT INTO poc VALUES (?, ?)", ("run-2", "offline"))
        writer.commit()
        assert reader.execute("SELECT count(*) FROM poc").fetchone() == (1,)
        writer.push()
        reader.pull()
        assert reader.execute("SELECT count(*) FROM poc").fetchone() == (2,)

        writer.execute("BEGIN")
        writer.execute("INSERT INTO poc VALUES (?, ?)", ("rollback", "discard"))
        writer.rollback()
        writer.push()
        reader.pull()
        assert reader.execute("SELECT count(*) FROM poc").fetchone() == (2,)
        print("PASS: push/pull, pre-push isolation, parameterized JSON, rollback")


if __name__ == "__main__":
    main()
