from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
SHA_ACTION = re.compile(r"^[^\s@]+@[0-9a-f]{40}$")


def _workflows() -> list[tuple[Path, dict]]:
    return [
        (path, yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader))
        for path in sorted(WORKFLOW_DIR.glob("*.yml"))
    ]


def test_workflows_pin_runners_actions_and_timeouts() -> None:
    for path, workflow in _workflows():
        assert isinstance(workflow.get("permissions"), dict), f"{path}: explicit permissions required"
        for job_name, job in workflow["jobs"].items():
            assert job.get("runs-on") == "ubuntu-24.04", f"{path}:{job_name}: pin runner image"
            assert int(job.get("timeout-minutes", 0)) > 0, f"{path}:{job_name}: timeout required"
            for step in job.get("steps", []):
                action = step.get("uses")
                if action:
                    assert SHA_ACTION.fullmatch(action), f"{path}: action must use a 40-char SHA: {action}"


def test_write_permissions_are_limited_to_expected_jobs() -> None:
    allowed = {
        ("daily-juslag.yml", "research", "contents"),
        ("daily-juslag.yml", "site", "pages"),
        ("daily-juslag.yml", "site", "id-token"),
        ("opening-bars.yml", "capture", "contents"),
    }
    actual = set()
    for path, workflow in _workflows():
        inherited = workflow.get("permissions", {})
        for job_name, job in workflow["jobs"].items():
            permissions = job.get("permissions", inherited)
            actual.update(
                (path.name, job_name, scope)
                for scope, access in permissions.items()
                if access == "write"
            )
    assert actual == allowed


def test_dependabot_monitors_github_actions() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    updates = config["updates"]
    assert any(
        entry["package-ecosystem"] == "github-actions" and entry["directory"] == "/"
        for entry in updates
    )
