from __future__ import annotations

import os

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from src.app.tools.gedweb_access import GEDWEB_URL


@pytest.mark.gedweb_playwright
def test_gedweb_is_accessible_with_playwright() -> None:
    """Valida o carregamento HTTP do GEDWeb em um ambiente autorizado."""

    if os.getenv("RUN_GEDWEB_PLAYWRIGHT", "0") != "1":
        pytest.skip("defina RUN_GEDWEB_PLAYWRIGHT=1 para executar o teste real")

    url = os.getenv("GEDWEB_PLAYWRIGHT_URL", GEDWEB_URL)
    timeout_ms = int(os.getenv("GEDWEB_PLAYWRIGHT_TIMEOUT_MS", "30000"))

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                assert response is not None, "o GEDWeb não retornou resposta HTTP"
                assert 200 <= response.status < 400, (
                    f"GEDWeb retornou HTTP {response.status}; "
                    "verifique a VPN/restrição de IP"
                )
                assert page.locator("body").count() == 1
            finally:
                browser.close()
    except PlaywrightError as exc:
        pytest.fail(f"Playwright não conseguiu acessar o GEDWeb: {exc}")
