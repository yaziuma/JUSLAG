from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_timer_runs_three_times_before_preflight() -> None:
    timer = (ROOT / "config/systemd/juslag-local-daily-report.timer").read_text(
        encoding="utf-8"
    )
    for hour in ("06", "07", "08"):
        assert f"OnCalendar=Mon..Fri *-*-* {hour}:00:00" in timer
    assert "OnCalendar=Mon..Fri *-*-* 08:40:00" in timer
    assert "Persistent=false" in timer


def test_service_loads_tracked_production_settings() -> None:
    service = (ROOT / "config/systemd/juslag-local-daily-report.service").read_text(
        encoding="utf-8"
    )
    assert (
        "Environment=JUSLAG_BACKTEST_SETTINGS_FILE="
        "config/production_backtest_settings.json" in service
    )
    assert (ROOT / "config/production_backtest_settings.json").is_file()
