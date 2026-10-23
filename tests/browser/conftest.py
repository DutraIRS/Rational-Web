import pytest

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        browser = None
        for channel in (None, "msedge", "chrome"):  # bundled Chromium, else an installed Chromium browser
            try:
                browser = p.chromium.launch(channel=channel) if channel else p.chromium.launch()
                break
            except Exception:
                continue
        if browser is None:
            pytest.skip("no Chromium available: run `playwright install chromium`")
        yield browser
        browser.close()
