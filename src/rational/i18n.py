"""Internationalization: message catalogs, locale negotiation, plurals and formatting.

    app = App(i18n=I18n({"en": {"hello": "Hello, {name}!"}, "pt": {"hello": "Olá, {name}!"}}))

    self.t("hello", name="Ada")          # inside a component
    ctx.t("items", count=3)              # anywhere a Context is available

Plural forms use dotted suffixes: ``items.one`` / ``items.other`` (plus ``.zero`` and ``.two`` if you
want them) and are chosen from the ``count`` parameter. The locale comes from the ``rw_lang`` cookie,
then the ``Accept-Language`` header, then the default. Switch it from the browser with
``js.set_locale("pt")``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

LANG_COOKIE = "rw_lang"


def _plural_category(count: float) -> str:
    if count == 0:
        return "zero"
    if count == 1:
        return "one"
    if count == 2:
        return "two"
    return "other"


class _Missing(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class I18n:
    """Message catalogs keyed by language tag (``"en"``, ``"pt-BR"``)."""

    def __init__(self, catalogs: Mapping[str, Mapping[str, str]], default: str | None = None) -> None:
        if not catalogs:
            raise ValueError("I18n needs at least one catalog")
        self.catalogs = {tag.lower(): dict(messages) for tag, messages in catalogs.items()}
        self.default = (default or next(iter(catalogs))).lower()
        if self.default not in self.catalogs:
            raise ValueError(f"default locale {self.default!r} has no catalog")

    @classmethod
    def from_directory(cls, path: str | Path, default: str | None = None) -> I18n:
        """Load ``<dir>/<tag>.json`` files (flat ``{"key": "message"}`` objects)."""
        catalogs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(path).glob("*.json"))}
        return cls(catalogs, default)

    @property
    def locales(self) -> list[str]:
        return list(self.catalogs)

    def resolve(self, tag: str | None) -> str | None:
        """The supported locale best matching ``tag`` (exact, then language-only), or ``None``."""
        if not tag:
            return None
        tag = tag.lower().replace("_", "-")
        if tag in self.catalogs:
            return tag
        base = tag.split("-")[0]
        if base in self.catalogs:
            return base
        return next((known for known in self.catalogs if known.split("-")[0] == base), None)

    def negotiate(self, cookie: str | None, accept_language: str | None) -> str:
        chosen = self.resolve(cookie)
        if chosen:
            return chosen
        ranked: list[tuple[float, str]] = []
        for part in (accept_language or "").split(","):
            tag, _, params = part.strip().partition(";")
            quality = 1.0
            if params.strip().startswith("q="):
                try:
                    quality = float(params.strip()[2:])
                except ValueError:
                    quality = 0.0
            if tag and quality > 0:
                ranked.append((quality, tag))
        for _quality, tag in sorted(ranked, key=lambda item: -item[0]):
            chosen = self.resolve(tag)
            if chosen:
                return chosen
        return self.default

    def translate(self, locale: str, key: str, **params: Any) -> str:
        """The message for ``key`` in ``locale`` (falling back to the default, then to the key)."""
        for tag in dict.fromkeys((locale, locale.split("-")[0], self.default)):
            catalog = self.catalogs.get(tag)
            if catalog is None:
                continue
            template = None
            if "count" in params and isinstance(params["count"], int | float):
                category = _plural_category(params["count"])
                template = catalog.get(f"{key}.{category}") or catalog.get(f"{key}.other")
            template = template if template is not None else catalog.get(key)
            if template is not None:
                try:
                    return template.format_map(_Missing(params))
                except (ValueError, IndexError, AttributeError):
                    return template
        return key
