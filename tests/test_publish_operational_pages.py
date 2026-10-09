import json

import pytest

from scripts.ops.publish_operational_pages import snapshots


def test_publication_bundle_requires_matching_ready_dependencies(tmp_path):
    root = tmp_path / "data/manual_strategy"
    (root / "preflight").mkdir(parents=True)
    (root / "orders").mkdir()
    preflight = {"as_of": "2026-10-09", "status": "READY", "sheet_sha256": "match",
        "order_sheet": "data/manual_strategy/orders/2026-10-09-entry.json"}
    (root / "preflight/2026-10-09.json").write_text(json.dumps(preflight))
    with pytest.raises(ValueError, match="missing its order sheet"):
        snapshots(tmp_path)
    sheet = {"as_of": "2026-10-06", "sheet_sha256": "match"}
    path = root / "orders/2026-10-09-entry.json"
    path.write_text(json.dumps(sheet))
    with pytest.raises(ValueError, match="do not match"):
        snapshots(tmp_path)
    sheet["as_of"] = "2026-10-09"
    path.write_text(json.dumps(sheet))
    (root / "secret.env").write_text("not for publication")
    assert set(snapshots(tmp_path)) == {
        "data/manual_strategy/preflight/2026-10-09.json",
        "data/manual_strategy/orders/2026-10-09-entry.json",
    }
