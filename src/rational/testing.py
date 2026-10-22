"""Test pages without a browser.

    client = TestClient(app)
    page = client.open("/")
    page.click("Increment")
    assert "Count: 1" in page.text

Events go through the real HTTP endpoint (cookies, CSRF, validation); patches
are applied to a lightweight DOM so later lookups see the updated page.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from html.parser import HTMLParser
from typing import Any

from starlette.testclient import TestClient as _StarletteClient

from .rendering.html import VOID_TAGS


class El:
    def __init__(self, tag: str, attrs: dict[str, str], parent: El | None = None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[El | str] = []

    @property
    def text(self) -> str:
        parts = [
            c if isinstance(c, str) else c.text
            for c in self.children
            if isinstance(c, str) or c.tag not in ("script", "style", "title")
        ]
        return " ".join(" ".join(parts).split())

    def iter(self) -> Iterator[El]:
        for child in self.children:
            if isinstance(child, El):
                yield child
                yield from child.iter()

    def find_all(self, tag: str | None = None, **attrs: str) -> list[El]:
        out = []
        for el in self.iter():
            if tag is not None and el.tag != tag:
                continue
            if all(el.attrs.get(k.replace("_", "-")) == v for k, v in attrs.items()):
                out.append(el)
        return out

    def get(self, name: str) -> str | None:
        return self.attrs.get(name)

    def __repr__(self) -> str:
        return f"<{self.tag} {self.attrs}>"


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = El("#root", {})
        self.current = self.root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        el = El(tag, {k: "" if v is None else v for k, v in attrs}, self.current)
        self.current.children.append(el)
        if tag not in VOID_TAGS:
            self.current = el

    def handle_endtag(self, tag: str) -> None:
        node: El | None = self.current
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.current = node.parent

    def handle_data(self, data: str) -> None:
        self.current.children.append(data)


def parse(html: str) -> El:
    parser = _Parser()
    parser.feed(html)
    parser.close()
    return parser.root


class EventFailedError(AssertionError):
    pass


class PageView:
    def __init__(self, client: TestClient, path: str, response: Any) -> None:
        self.client = client
        self.path = path
        self.status_code: int = response.status_code
        self.dom = parse(response.text)
        manifest = self.dom.find_all("script", id="rw-manifest")
        self.manifest: dict[str, Any] | None = json.loads(manifest[0].text) if manifest else None
        self.last: dict[str, Any] = {}

    @property
    def text(self) -> str:
        body = self.dom.find_all("body")
        return (body[0] if body else self.dom).text

    @property
    def html(self) -> str:
        return _serialize(self.dom)

    # -- finding -----------------------------------------------------------------------------

    def find(self, text: str, event: str) -> El:
        """The element handling ``event`` whose accessible name (``aria-label``, else its text) contains
        ``text``; the closest match wins."""
        attr = f"data-rw-on-{event}"
        named = [(el, el.get("aria-label") or el.text) for el in self.dom.iter() if attr in el.attrs]
        matches = [(el, name) for el, name in named if text in name]
        if not matches:
            raise LookupError(f"no element with {attr} named {text!r}")
        best: El = min(matches, key=lambda pair: len(pair[1]))[0]
        return best

    def field(self, label: str) -> El:
        for lab in self.dom.find_all("label"):
            if label in lab.text and lab.get("for"):
                found = self.dom.find_all(id=lab.get("for") or "")
                if found:
                    return found[0]
        raise LookupError(f"no form control labelled {label!r}")

    # -- interacting ---------------------------------------------------------------------------

    def click(self, text: str) -> dict[str, Any]:
        return self.fire(self.find(text, "click").attrs["data-rw-on-click"], {})

    def input(self, label: str, value: Any, event: str = "input") -> dict[str, Any]:
        el = self.field(label)
        handler = el.get(f"data-rw-on-{event}")
        if handler is None:
            raise LookupError(f"control {label!r} has no on_{event} handler")
        return self.fire(handler, {"value": value})

    def submit(self, data: dict[str, Any], *, button: str | None = None, check: bool = True) -> dict[str, Any]:
        forms = [f for f in self.dom.find_all("form") if "data-rw-on-submit" in f.attrs]
        if button is not None:
            forms = [f for f in forms if button in f.text]
        if not forms:
            raise LookupError("no form with an on_submit handler")
        return self.fire(forms[0].attrs["data-rw-on-submit"], {"form": data}, check=check)

    def fire(self, handler: str, payload: dict[str, Any], *, check: bool = True) -> dict[str, Any]:
        if self.manifest is None:
            raise EventFailedError("page is not interactive")
        response = self.client.http.post(
            self.manifest["endpoint"],
            json={
                "v": self.manifest["v"],
                "page": self.manifest["page"],
                "rev": self.manifest["rev"],
                "handler": handler,
                "payload": payload,
            },
            headers={"X-RW-CSRF": self.manifest["csrf"]},
        )
        data: dict[str, Any] = response.json()
        self.last = data
        self.manifest["rev"] = data.get("rev", self.manifest["rev"])
        if data.get("csrf"):
            self.manifest["csrf"] = data["csrf"]
        for patch in data.get("patches", []):
            self._apply(patch)
        if (
            check
            and "error" in data
            and data["error"]["code"]
            not in (
                "validation_error",
                "stale",
                "stale_revision",
            )
        ):
            raise EventFailedError(f"{response.status_code}: {data['error']}")
        return data

    def _apply(self, patch: dict[str, Any]) -> None:
        targets = self.dom.find_all(data_rw_c=patch["id"])
        if not targets:
            return
        old = targets[0]
        new = parse(patch["html"]).children[0]
        assert isinstance(new, El) and old.parent is not None
        index = old.parent.children.index(old)
        new.parent = old.parent
        old.parent.children[index] = new


class TestClient:
    __test__ = False  # not a pytest test class

    def __init__(self, app: Any) -> None:
        self.app = app
        self.http = _StarletteClient(app)

    def __enter__(self) -> TestClient:
        self.http.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.http.__exit__(*exc)

    def open(self, path: str) -> PageView:
        return PageView(self, path, self.http.get(path, headers={"accept": "text/html"}))


def _serialize(el: El) -> str:
    from .rendering.html import escape_attr, escape_text

    parts: list[str] = []
    for child in el.children:
        if isinstance(child, str):
            parts.append(escape_text(child))
            continue
        attrs = "".join(f' {k}="{escape_attr(v)}"' for k, v in child.attrs.items())
        parts.append(f"<{child.tag}{attrs}>")
        if child.tag not in VOID_TAGS:
            parts.append(_serialize(child) + f"</{child.tag}>")
    return "".join(parts)
