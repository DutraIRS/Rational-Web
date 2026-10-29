"""Search engines and link previews: head tags, sitemap.xml, robots.txt and their export."""

import asyncio
import json
import re

import pytest

from rational import App, Page, Text
from rational.export import export_site
from rational.seo import Seo, structured
from rational.testing import TestClient


def site():
    app = App(title="Shop")
    Seo(app, site_url="https://me.github.io/shop/", image="/assets/preview.png", twitter="@shop", disallow=["/admin"])

    @app.page("/")
    class Home(Page):
        title = "Shop"
        description = 'Fine "things" & more'

        def render(self):
            return Text("Home")

    @app.page("/{lang}/products/{slug}.html", paths=[{"lang": "en", "slug": "mug"}, {"lang": "es", "slug": "mug"}])
    class Product(Page):  # {lang} sets the page's language
        slug: str

        def mount(self):
            self.title = f"Mug ({self.lang})"
            self.image = "https://cdn.example/mug.png"
            self.alternates = {"en": "/en/products/mug.html", "es": "/es/products/mug.html"}
            self.structured_data = structured("Product", name="Mug </script> deluxe")

        def render(self):
            return Text("Mug")

    @app.page("/drafts")
    class Drafts(Page):
        noindex = True

        def render(self):
            return Text("Drafts")

    @app.page("/account", auth="required")
    class Account(Page):
        def render(self):
            return Text("Account")

    @app.page("/orders/{order_id}")  # no paths=: not listed
    class Order(Page):
        order_id: int

        def render(self):
            return Text(str(self.order_id))

    return app


def head_of(html):
    return html[html.index("<head>") : html.index("</head>")]


def test_pages_get_canonical_urls_and_link_previews():
    client = TestClient(site())
    head = head_of(client.http.get("/").text)
    assert '<link rel="canonical" href="https://me.github.io/shop/">' in head
    assert '<meta property="og:description" content="Fine &quot;things&quot; &amp; more">' in head
    assert '<meta property="og:image" content="https://me.github.io/shop/assets/preview.png">' in head
    assert '<meta name="twitter:card" content="summary_large_image">' in head
    assert '<meta name="twitter:site" content="@shop">' in head and 'name="robots"' not in head

    head = head_of(client.http.get("/es/products/mug.html").text)
    assert '<meta property="og:title" content="Mug (es)">' in head and 'content="es"' in head
    assert '<meta property="og:image" content="https://cdn.example/mug.png">' in head
    assert '<link rel="alternate" hreflang="en" href="https://me.github.io/shop/en/products/mug.html">' in head
    data = re.search(r'<script type="application/ld\+json">(.*?)</script>', head).group(1)
    assert "</script> deluxe" not in data  # escaped so it cannot close the element
    assert json.loads(data) == {"@context": "https://schema.org", "@type": "Product", "name": "Mug </script> deluxe"}

    assert '<meta name="robots" content="noindex">' in head_of(client.http.get("/drafts").text)


def test_sitemap_and_robots_list_public_pages():
    client = TestClient(site())
    sitemap = client.http.get("/sitemap.xml")
    assert sitemap.headers["content-type"].startswith("application/xml")
    locs = re.findall(r"<loc>(.*?)</loc>", sitemap.text)
    assert locs == [
        "https://me.github.io/shop/",
        "https://me.github.io/shop/en/products/mug.html",
        "https://me.github.io/shop/es/products/mug.html",
    ]  # not the noindex, sign-in or unlisted parameter pages
    robots = client.http.get("/robots.txt").text
    assert robots == "User-agent: *\nDisallow: /admin\nAllow: /\nSitemap: https://me.github.io/shop/sitemap.xml\n"


def test_a_static_export_writes_the_sitemap_and_robots(tmp_path):
    report = asyncio.run(export_site(site(), tmp_path))
    assert {"/sitemap.xml", "/robots.txt"} <= set(report.assets)
    assert "mug.html" in (tmp_path / "sitemap.xml").read_text("utf-8")
    assert (tmp_path / "robots.txt").read_text("utf-8").startswith("User-agent: *")


def test_pages_without_seo_or_an_image():
    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return Text("Home")

    assert "og:" not in TestClient(app).http.get("/").text  # no Seo: no tags
    Seo(app, site_url="https://x.example")
    head = head_of(TestClient(app).http.get("/").text)
    assert '<meta name="twitter:card" content="summary">' in head and "og:image" not in head
    with pytest.raises(ValueError, match="absolute URL"):
        Seo(App(), site_url="x.example")
