from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_timer_runs_after_daily_publish_and_catches_up() -> None:
    timer = (ROOT / "config/systemd/juslag-turso-reconcile.timer").read_text(encoding="utf-8")
    assert "OnCalendar=Mon..Fri *-*-* 10:15:00" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=0" in timer


def test_service_is_read_only_and_loads_local_credentials() -> None:
    service = (ROOT / "config/systemd/juslag-turso-reconcile.service").read_text(encoding="utf-8")
    assert "EnvironmentFile=%h/projects/JUSLAG/.env.turso" in service
    assert "scripts/ops/audit_turso_from_origin.sh" in service
    assert "--repair" not in service


def test_audit_uses_fresh_origin_data_without_repair() -> None:
    script = (ROOT / "scripts/ops/audit_turso_from_origin.sh").read_text(encoding="utf-8")
    assert "fetch --quiet origin main" in script
    assert "archive --format=tar origin/main data/reports data/history.jsonl" in script
    assert "--repair" not in script

