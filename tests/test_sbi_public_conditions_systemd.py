from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_timer_captures_after_publication_and_before_open() -> None:
    timer = (ROOT / "config/systemd/juslag-sbi-public-conditions.timer").read_text(encoding="utf-8")
    assert "OnCalendar=Mon..Fri *-*-* 08:45:00" in timer
    assert "OnCalendar=Mon..Fri *-*-* 19:10:00" in timer
    assert "Persistent=false" in timer
    assert "RandomizedDelaySec=0" in timer


def test_service_uses_public_collector_without_credentials() -> None:
    service = (ROOT / "config/systemd/juslag-sbi-public-conditions.service").read_text(encoding="utf-8")
    assert "capture_sbi_public_conditions.py" in service
    assert "EnvironmentFile=" not in service
    assert "--repair" not in service


def test_workflow_has_both_jst_collection_windows() -> None:
    workflow = (ROOT / ".github/workflows/sbi-public-conditions.yml").read_text(encoding="utf-8")
    assert 'cron: "45 23 * * 0-4"' in workflow
    assert 'cron: "10 10 * * 1-5"' in workflow
    assert "data/sbi_execution_conditions/" in workflow

