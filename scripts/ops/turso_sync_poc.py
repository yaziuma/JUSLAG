"""Exercise Turso Sync against a disposable local sync server."""

import argparse
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import turso.sync


def wait_for_server(port: int, process: subprocess.Popen[bytes]) -> None:
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError(f"sync server exited with {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError("sync server did not start")


@contextmanager
def local_server(binary: Path, database: Path, port: int, log: Path):
    with log.open("ab") as output:
        process = subprocess.Popen(
            [str(binary), str(database), "--sync-server", f"127.0.0.1:{port}"],
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_for_server(port, process)
            yield
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def exercise(url: str, root: Path) -> None:
    writer = turso.sync.connect(path=str(root / "writer.db"), remote_url=url)
    reader = turso.sync.connect(path=str(root / "reader.db"), remote_url=url)

    writer.execute("CREATE TABLE poc (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    writer.commit()
    writer.execute("INSERT INTO poc VALUES (?, ?)", ("run-1", '{"ok":true}'))
    writer.commit()
    writer.push()
    reader.pull()
    assert reader.execute("SELECT payload FROM poc WHERE id = ?", ("run-1",)).fetchone() == ('{"ok":true}',)

    writer.execute("INSERT INTO poc VALUES (?, ?)", ("run-2", "pending"))
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18080")
    parser.add_argument("--server-bin", type=Path, help="start disposable server and test outage recovery")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="juslag-turso-poc-") as directory:
        root = Path(directory)
        if not args.server_bin:
            exercise(args.url, root)
            return

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        database = root / "server.db"
        log = root / "server.log"
        with local_server(args.server_bin, database, port, log):
            exercise(url, root)

        writer = turso.sync.connect(
            path=str(root / "writer.db"), remote_url=url, bootstrap_if_empty=False
        )
        writer.execute("INSERT INTO poc VALUES (?, ?)", ("offline", "stored locally"))
        writer.commit()
        try:
            writer.push()
        except Exception as exc:
            if "network error" not in str(exc):
                raise
        else:
            raise AssertionError("push unexpectedly succeeded while server was stopped")

        with local_server(args.server_bin, database, port, log):
            writer.push()
            fresh = turso.sync.connect(path=str(root / "fresh.db"), remote_url=url)
            assert fresh.execute("SELECT count(*) FROM poc").fetchone() == (3,)
            assert fresh.execute("SELECT payload FROM poc WHERE id = ?", ("offline",)).fetchone() == (
                "stored locally",
            )
        print("PASS: offline write, failed push, server restart, retry, fresh-client bootstrap")
        if "no such table: turso_sync_last_change_id" in log.read_text():
            print("WARN: sync server reported missing internal table")


if __name__ == "__main__":
    main()
