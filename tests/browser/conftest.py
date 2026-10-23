import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")

ENGINE = os.environ.get("RATIONAL_BROWSER", "chromium")  # chromium, firefox or webkit


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        engine = getattr(p, ENGINE)
        browser = None
        # Chromium may also be an installed Edge or Chrome; the other engines need `playwright install`.
        for channel in (None, "msedge", "chrome") if ENGINE == "chromium" else (None,):
            try:
                browser = engine.launch(channel=channel) if channel else engine.launch()
                break
            except Exception:
                continue
        if browser is None:
            pytest.skip(f"no {ENGINE} available: run `playwright install {ENGINE}`")
        yield browser
        browser.close()
