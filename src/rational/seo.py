"""Search engines and link previews: ``sitemap.xml``, ``robots.txt`` and the tags in each page's head.

::

    Seo(app, site_url="https://shop.example", site_name="Shop", image="/assets/preview.png")

Every page then gets a canonical URL, Open Graph and Twitter tags (the preview shown when a link
is shared) built from its ``title``, ``description`` and ``image``, ``hreflang`` links to its
translations (``alternates``), its structured data (``structured_data``, as JSON-LD) and, for
``noindex = True``, a request not to be indexed. ``/sitemap.xml`` lists every public page (with
the ``paths=`` of parameter routes) and a static export writes both files.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape as xml_escape

from fastapi.responses import PlainTextResponse, Response

from .document import json_for_script
from .rendering.html import escape_attr

if TYPE_CHECKING:
    from .app import App
    from .component import Page


class Seo:
    """Installs ``/sitemap.xml``, ``/robots.txt`` and per-page head tags on ``app``.

    ``site_url`` is the public address, with any sub-path (``"https://me.github.io/site"``).
    ``image`` is the default preview image; ``disallow`` lists paths crawlers should skip.
    """

    def __init__(
        self,
        app: App,
        *,
        site_url: str,
        site_name: str | None = None,
        image: str | None = None,
        twitter: str | None = None,
        disallow: Sequence[str] = (),
    ) -> None:
        if not site_url.startswith(("https://", "http://")):
            raise ValueError("site_url must be an absolute URL, like https://shop.example")
        self.app = app
        self.site_url = site_url.rstrip("/")
        self.site_name = site_name or app.title
        self.image = image
        self.twitter = twitter
        self.disallow = tuple(disallow)
        app.seo = self
        app.fastapi.add_api_route("/sitemap.xml", self.sitemap, methods=["GET"], include_in_schema=False)
        app.fastapi.add_api_route("/robots.txt", self.robots, methods=["GET"], include_in_schema=False)
        app.exported_files += ["/sitemap.xml", "/robots.txt"]

    def absolute(self, url: str) -> str:
        """``url`` on this site, made absolute (absolute URLs are returned as they are)."""
        return url if url.startswith(("https://", "http://")) else self.site_url + "/" + url.lstrip("/")

    def head(self, page: Page, path: str, title: str, lang: str) -> str:
        """The tags for one page, served at ``path``."""
        url = self.absolute(page.canonical or path)
        tags = [f'<link rel="canonical" href="{escape_attr(url)}">']
        if page.noindex:
            tags.append('<meta name="robots" content="noindex">')
        meta = {
            "og:type": "website",
            "og:site_name": self.site_name,
            "og:title": title,
            "og:description": page.description,
            "og:url": url,
            "og:locale": lang.replace("-", "_"),
        }
        image = page.image or self.image
        if image:
            meta["og:image"] = self.absolute(image)
        tags += [f'<meta property="{k}" content="{escape_attr(v)}">' for k, v in meta.items() if v]
        tags.append(f'<meta name="twitter:card" content="{"summary_large_image" if image else "summary"}">')
        if self.twitter:
            tags.append(f'<meta name="twitter:site" content="{escape_attr(self.twitter)}">')
        for language, href in (page.alternates or {}).items():
            tags.append(
                f'<link rel="alternate" hreflang="{escape_attr(language)}" href="{escape_attr(self.absolute(href))}">'
            )
        if page.structured_data is not None:
            tags.append(f'<script type="application/ld+json">{json_for_script(page.structured_data)}</script>')
        return "".join(tags)

    def urls(self) -> list[str]:
        """Every public page: no sign-in, not ``noindex``, parameter routes through ``paths=``."""
        urls = []
        for route in self.app.routes.values():
            if (route.auth or "") == "required" or route.page.noindex or route.path == "/404.html":
                continue
            urls += route.urls()
        return urls

    async def sitemap(self) -> Response:
        entries = "".join(f"<url><loc>{xml_escape(self.absolute(url))}</loc></url>" for url in self.urls())
        xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'
        return Response(xml, media_type="application/xml")

    async def robots(self) -> Response:
        lines = ["User-agent: *", *(f"Disallow: {path}" for path in self.disallow), "Allow: /"]
        lines.append(f"Sitemap: {self.site_url}/sitemap.xml")
        return PlainTextResponse("\n".join(lines) + "\n")


def structured(kind: str, **fields: Any) -> dict[str, Any]:
    """A schema.org object for ``structured_data``: ``structured("Article", headline=...)``."""
    return {"@context": "https://schema.org", "@type": kind, **fields}
