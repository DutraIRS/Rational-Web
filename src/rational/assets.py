"""External stylesheets and scripts, and the optional Bootstrap and Tailwind adapters.

    App(adapter=bootstrap())                                   # pinned CDN build with integrity hashes
    App(adapter=tailwind(css="/static/tailwind.css"))          # CSS you built with the Tailwind CLI
    App(stylesheets=["/static/site.css"], scripts=[Asset("https://cdn.example/x.js", integrity="sha384-...")])

Assets are added to every page's ``<head>``. Root-relative URLs are served from this app (mount the
directory with ``app.static``) and honour ``--root-path``; absolute ``https://`` URLs are allowed and, with
``App(csp=True)``, their origin is added to the Content-Security-Policy for exactly that kind of asset.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .rendering.html import escape_attr

BOOTSTRAP_INTEGRITY = {
    "5.3.3": (
        "sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH",
        "sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz",
    )
}


@dataclass(frozen=True)
class Asset:
    """A stylesheet or script URL, with optional Subresource Integrity."""

    href: str
    integrity: str | None = None
    crossorigin: str | None = None

    def __post_init__(self) -> None:
        parts = urlsplit(self.href)
        local = self.href.startswith("/") and not self.href.startswith(("//", "/\\"))
        if not local and not (parts.scheme == "https" and parts.netloc):
            raise ValueError(f"asset {self.href!r}: use a root-relative path or an absolute https:// URL")

    @property
    def origin(self) -> str | None:
        """``https://host`` for external assets, ``None`` for ones served by this app."""
        if self.href.startswith("/"):
            return None
        parts = urlsplit(self.href)
        return f"{parts.scheme}://{parts.netloc}"


def as_asset(value: str | Asset) -> Asset:
    return value if isinstance(value, Asset) else Asset(value)


@dataclass(frozen=True)
class Adapter:
    """A bundle of assets that makes a CSS framework available to every page."""

    stylesheets: tuple[Asset, ...] = ()
    scripts: tuple[Asset, ...] = ()
    needs_inline_styles: bool = False  # incompatible with a strict CSP
    notes: str = field(default="", compare=False)


def bootstrap(version: str = "5.3.3", *, js: bool = False, integrity: Sequence[str] | None = None) -> Adapter:
    """Bootstrap from jsDelivr. ``js=True`` adds the bundle (dropdowns, collapse, ...).

    Only versions with known integrity hashes are built in; for another version pass
    ``integrity=(css_hash, js_hash)`` yourself.
    """
    hashes = tuple(integrity) if integrity is not None else BOOTSTRAP_INTEGRITY.get(version)
    if hashes is None or len(hashes) != 2:
        raise ValueError(
            f"bootstrap {version}: pass integrity=(css_hash, js_hash); built in: {sorted(BOOTSTRAP_INTEGRITY)}"
        )
    base = f"https://cdn.jsdelivr.net/npm/bootstrap@{version}/dist"
    css = Asset(f"{base}/css/bootstrap.min.css", hashes[0], "anonymous")
    scripts = (Asset(f"{base}/js/bootstrap.bundle.min.js", hashes[1], "anonymous"),) if js else ()
    return Adapter(stylesheets=(css,), scripts=scripts)


def tailwind(css: str | None = None, *, play_cdn: bool = False) -> Adapter:
    """Tailwind, either from CSS you built (recommended) or the Play CDN (prototyping only).

    Build with the Tailwind CLI, pointing its content globs at your ``*.py`` files, and serve the output with
    ``app.static``. The Play CDN compiles in the browser, is not pinned, and needs inline styles, so it
    cannot be used with ``App(csp=True)``.
    """
    if bool(css) == play_cdn:
        raise ValueError("tailwind(): pass either css='/static/tailwind.css' or play_cdn=True")
    if css:
        return Adapter(stylesheets=(Asset(css),))
    return Adapter(
        scripts=(Asset("https://cdn.tailwindcss.com"),),
        needs_inline_styles=True,
        notes="Tailwind Play CDN: development only",
    )


def cx(*parts: Any) -> str:
    """Join class names: strings, ``None``/``False`` are skipped, mappings include keys whose value is truthy.

    cx("btn", {"btn-primary": primary, "disabled": busy}, size and f"btn-{size}")
    """
    names: list[str] = []
    for part in parts:
        if not part:
            continue
        if isinstance(part, str):
            names.append(part)
        elif isinstance(part, Mapping):
            names.extend(name for name, on in part.items() if on)
        else:
            names.append(cx(*part))
    return " ".join(names)


def render_assets(styles: Sequence[Asset], scripts: Sequence[Asset], base: str = "", nonce: str | None = None) -> str:
    def href(asset: Asset) -> str:
        return escape_attr(base + asset.href if asset.href.startswith("/") else asset.href)

    def extras(asset: Asset) -> str:
        out = ""
        if asset.integrity:
            out += f' integrity="{escape_attr(asset.integrity)}"'
        if asset.crossorigin:
            out += f' crossorigin="{escape_attr(asset.crossorigin)}"'
        return out

    nonce_attr = f' nonce="{escape_attr(nonce)}"' if nonce else ""
    parts = [f'<link rel="stylesheet" href="{href(a)}"{extras(a)}>' for a in styles]
    parts += [f'<script src="{href(a)}" defer{extras(a)}{nonce_attr}></script>' for a in scripts]
    return "".join(parts)
