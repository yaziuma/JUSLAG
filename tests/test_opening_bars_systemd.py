from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_timer_has_two_precise_nonpersistent_schedules() -> None:
    timer = (ROOT / "config/systemd/juslag-opening-bars.timer").read_text(encoding="utf-8")
    assert "OnCalendar=Mon..Fri *-*-* 09:16:00" in timer
    assert "OnCalendar=Mon..Fri *-*-* 09:40:00" in timer
    assert "AccuracySec=10s" in timer
    assert "RandomizedDelaySec=0" in timer
    assert "Persistent=false" in timer


def test_service_uses_observation_version_capture() -> None:
    service = (ROOT / "config/systemd/juslag-opening-bars.service").read_text(encoding="utf-8")
    assert "WorkingDirectory=%h/projects/JUSLAG" in service
    assert "scripts/ops/capture_intraday.py" in service
    assert "--snapshot-dir data/opening_bars" in service
    assert "Restart=" not in service
