from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_monitor_avoids_stale_queue_backlog() -> None:
    timer = (ROOT / "config/systemd/juslag-codex-monitor.timer").read_text()
    assert "Persistent=false" in timer
    assert "08:43:00" not in timer
    assert "08:50:00" not in timer
    assert "09:10:00" not in timer


def test_monitor_records_queue_time() -> None:
    script = (ROOT / "scripts/ops/queue_codex_operations_check.sh").read_text()
    assert "queued_at=$(date --iso-8601=seconds)" in script
    assert "queued_at=${queued_at}" in script
