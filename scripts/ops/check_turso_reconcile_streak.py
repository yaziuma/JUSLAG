"""Check consecutive scheduled Turso audits using GitHub Actions run logs."""
from __future__ import annotations

import argparse
import json
import subprocess

REPO = "yaziuma/JUSLAG"
WORKFLOW = "turso-reconcile.yml"
AUDIT_OK = "Audit: 0 date(s) require repair since 2026-09-18"


def scheduled_runs(runs: list[dict]) -> list[dict]:
    return sorted(
        (run for run in runs if run["event"] == "schedule"),
        key=lambda run: run["createdAt"],
        reverse=True,
    )


def run_passes(run: dict, log: str) -> bool:
    return (
        run["status"] == "completed"
        and run["conclusion"] == "success"
        and AUDIT_OK in log
    )


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=10)
    args = parser.parse_args()
    if args.target < 1:
        parser.error("--target must be positive")

    runs = scheduled_runs(json.loads(gh(
        "run", "list", "--repo", REPO, "--workflow", WORKFLOW,
        "--limit", "100", "--json",
        "databaseId,event,status,conclusion,createdAt,url",
    )))
    streak = 0
    for run in runs:
        log = ""
        if run["status"] == "completed" and run["conclusion"] == "success":
            log = gh("run", "view", str(run["databaseId"]), "--repo", REPO, "--log")
        passed = run_passes(run, log)
        print(f"{'PASS' if passed else 'FAIL'} {run['createdAt']} {run['url']}")
        if not passed:
            break
        streak += 1
        if streak == args.target:
            break
    print(f"Scheduled clean-audit streak: {streak}/{args.target}")
    if streak < args.target:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
