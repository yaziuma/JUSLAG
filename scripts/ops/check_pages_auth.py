#!/usr/bin/env python3
"""Verify that the deployed GitHub Pages site accepts the local password."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SITE_URL = "https://yaziuma.github.io/JUSLAG/"


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env.local")

    password = os.environ.get("JUSLAG_SITE_PASSWORD")
    if not password:
        raise SystemExit("JUSLAG_SITE_PASSWORD is not set in .env.local or the environment")

    site_url = os.environ.get("JUSLAG_SITE_URL", DEFAULT_SITE_URL)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            response = page.goto(site_url, wait_until="domcontentloaded", timeout=30_000)
            if response is None or not response.ok:
                status = response.status if response else "no response"
                raise RuntimeError(f"site returned {status}: {site_url}")

            password_input = page.locator("#staticrypt-password")
            password_input.wait_for(state="visible", timeout=10_000)
            password_input.fill(password)
            page.locator("#staticrypt-form").evaluate("form => form.requestSubmit()")
            page.wait_for_function(
                "!document.documentElement.classList.contains('staticrypt-html')",
                timeout=15_000,
            )
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "authentication did not complete; check JUSLAG_SITE_PASSWORD and the deployed site"
            ) from exc
        finally:
            browser.close()

    print(f"Pages authentication succeeded: {site_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
