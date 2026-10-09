"""Publish locally generated operating snapshots using the fixed Git checkout."""
from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
from pathlib import Path


def git(checkout: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(checkout), *args], text=True).strip()


def snapshots(source: Path) -> dict[str, bytes]:
    result = {}
    base = source / "data/manual_strategy"
    for directory in ("preflight", "orders", "signals", "intents"):
        for path in sorted((base / directory).glob("*.json")):
            data = path.read_bytes()
            json.loads(data)
            result[path.relative_to(source).as_posix()] = data
    for name, data in result.items():
        if "/preflight/" not in name:
            continue
        preflight = json.loads(data)
        date = preflight["as_of"]
        if Path(name).stem != date:
            raise ValueError("preflight date does not match filename")
        if preflight.get("status") != "READY":
            continue
        sheet_path = preflight["order_sheet"]
        if sheet_path not in result:
            raise ValueError("READY preflight is missing its order sheet")
        sheet = json.loads(result[sheet_path])
        if sheet["as_of"] != date or sheet["sheet_sha256"] != preflight["sheet_sha256"]:
            raise ValueError("preflight and order sheet do not match")
        signal_path = preflight.get("source_report", "")
        if "/manual_strategy/signals/" in signal_path and signal_path not in result:
            raise ValueError("preflight is missing its source signal")
        intent_path = preflight.get("execution_intent")
        if intent_path and intent_path not in result:
            raise ValueError("preflight is missing its execution intent")
    return result


def publish(source: Path, checkout: Path) -> int:
    payloads = snapshots(source)
    with Path(str(checkout) + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (checkout / ".git").exists():
            subprocess.run(["git", "clone", "--no-checkout", git(source, "remote", "get-url", "origin"),
                            str(checkout)], check=True)
            git(checkout, "switch", "--detach", "origin/main")
        if git(checkout, "status", "--porcelain"):
            raise RuntimeError("publication checkout has uncommitted changes")
        git(checkout, "fetch", "origin", "main")
        git(checkout, "merge", "--ff-only", "origin/main")
        changed = []
        for name, data in payloads.items():
            target = checkout / name
            if target.is_file() and target.read_bytes() == data:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            changed.append(name)
        if not changed:
            print("operational Pages data is current")
            return 0
        git(checkout, "add", "--", *changed)
        git(checkout, "commit", "-m", "data: publish current local operational snapshots")
        for attempt in range(3):
            try:
                git(checkout, "push", "origin", "HEAD:main")
                print(f"published {len(changed)} operational files")
                return len(changed)
            except subprocess.CalledProcessError:
                if attempt == 2:
                    raise
                git(checkout, "fetch", "origin", "main")
                git(checkout, "rebase", "origin/main")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--checkout", type=Path, default=Path("/tmp/juslag-push"))
    args = parser.parse_args()
    publish(args.source.resolve(), args.checkout.resolve())


if __name__ == "__main__":
    main()
