from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from juslag.services.site import render_site


def test_order_expiry_uses_viewing_time_and_updates_all_live_labels(tmp_path: Path):
    playwright = pytest.importorskip("playwright.sync_api")
    render_site([], [{"date": "2026-10-13", "backtest": {"judge": {
        "overall_score": 78, "overall_decision": "pass",
    }}}], tmp_path, capital_simulation={
        "strategy_name": "pca_sub_long_5d_manual_v2",
        "judge": {"overall_score": 78, "overall_decision": "pass"},
    }, operational={
        "rendered_at": "2026-10-13T08:42:00+09:00",
        "preflight": {"strategy_id": "pca_sub_long_5d_manual_v2", "as_of": "2026-10-13", "status": "READY", "action": "ENTRY"},
        "intent": {"expires_at": "2026-10-13T08:55:00+09:00"},
    })
    html = (tmp_path / "index.html").read_text()
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(timezone_id="America/New_York")
            context.route("**/*", lambda route: route.abort())
            page = context.new_page()
            before_deadline = datetime(2026, 10, 13, 8, 54, 59, tzinfo=ZoneInfo("Asia/Tokyo"))
            page.clock.install(time=before_deadline - timedelta(seconds=1))
            page.clock.pause_at(before_deadline)
            page.set_content(html, wait_until="domcontentloaded")
            assert page.locator("#operation-decision-word").text_content() == "発注準備完了"
            page.clock.run_for(1000)
            assert page.locator("#operation-decision-word").text_content() == "発注準備完了"
            page.clock.run_for(1000)
            assert page.locator("#operation-decision-word").text_content() == "期限切れ"
            assert "blocked" in page.locator("#operation-decision").get_attribute("class")
            assert "execute" not in page.locator("#operation-decision").get_attribute("class")
            assert "発注候補:" not in page.locator("#operation-order-gate").text_content()
            assert "運用結果: 期限切れ" in page.locator("#operation-summary").text_content()
            assert "運用結果: 発注準備完了" not in page.locator("#operation-summary").text_content()

            for event in ("initial", "pageshow", "visibilitychange"):
                page = context.new_page()
                now = datetime(2026, 10, 13, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
                before = datetime(2026, 10, 13, 8, 42, tzinfo=ZoneInfo("Asia/Tokyo"))
                start = now if event == "initial" else before
                page.clock.install(time=start - timedelta(seconds=1))
                page.clock.pause_at(start)
                page.set_content(html, wait_until="domcontentloaded")
                if event != "initial":
                    page.clock.set_system_time(now)
                    page.evaluate("event => (event === 'pageshow' ? window : document).dispatchEvent(new Event(event))", event)
                assert page.locator("#operation-decision-word").text_content() == "期限切れ"
                assert "この注文intentは期限切れです" in page.locator("#operation-order-gate").text_content()
        finally:
            browser.close()
