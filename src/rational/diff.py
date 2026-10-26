"""Fine-grained patches: compare a component's previous and new resolved trees.

A patch is a list of *edits*, each ``[kind, path, tag, arg]``. ``path`` is the chain of element-child
indices from the component's root element (text nodes are not counted, so adjacent text merging in the
browser cannot shift it) and ``tag`` is the tag the browser must find there; a mismatch makes the browser
ask for a full resync instead of guessing.

``["a", path, tag, {name: value | null}]``  set or remove attributes
``["t", path, tag, text]``                  replace the text of an element that holds only text
``["h", path, tag, html]``                  morph this element to new markup (the safe, coarse fallback)

Anything that is not a plain text or attribute change (added, removed or reordered children, raw HTML,
different tags) falls back to ``h`` for the smallest element that contains it.
"""

from __future__ import annotations

from typing import Any

from .rendering.html import VOID_TAGS, to_html
from .rendering.nodes import Node, RawHTML, TextNode

Edit = list[Any]

MAX_EDITS = 64  # past this, one coarse patch is cheaper than many small ones
KEY_ATTRS = ("data-rw-key", "data-rw-c")


def diff(old: Node, new: Node) -> list[Edit] | None:
    """Edits turning ``old`` into ``new``; ``[]`` if identical, ``None`` if one coarse patch is better."""
    edits: list[Edit] = []
    if not _diff(old, new, [], edits) or len(edits) > MAX_EDITS:
        return None
    return edits


def _attrs(node: Node) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, value in node.attrs:
        if value is None or value is False:
            continue
        out[name] = "" if value is True else str(value)
    return out


def _children(node: Node) -> list[Any]:
    """Children as the browser will see them: empty text dropped, adjacent text merged."""
    out: list[Any] = []
    for child in node.children:
        if isinstance(child, TextNode):
            if not child.text:
                continue
            if out and isinstance(out[-1], TextNode):
                out[-1] = TextNode(out[-1].text + child.text)
                continue
        out.append(child)
    return out


def _identity(node: Node) -> tuple[str | None, ...]:
    attrs = _attrs(node)
    return tuple(attrs.get(name) for name in KEY_ATTRS) + (attrs.get("id"),)


def _replace(new: Node, path: list[int], old_tag: str, edits: list[Edit]) -> bool:
    edits.append(["h", list(path), old_tag, to_html(new)])
    return True


def _diff(old: Node, new: Node, path: list[int], edits: list[Edit]) -> bool:
    if old is new or old == new:
        return True
    if old.tag != new.tag or _identity(old) != _identity(new) or old.tag == "rw-island":
        # A client component's inside belongs to the browser: send it whole, the browser keeps its state.
        return _replace(new, path, old.tag, edits)

    old_kids, new_kids = _children(old), _children(new)
    if old.tag in VOID_TAGS:
        old_kids = new_kids = []
    if any(isinstance(c, RawHTML) for c in old_kids + new_kids):
        if old_kids == new_kids:
            return _attrs_only(old, new, path, edits)
        return _replace(new, path, old.tag, edits)

    text_only = all(isinstance(c, TextNode) for c in old_kids + new_kids)
    if text_only:
        _attr_edit(old, new, path, edits)
        old_text = "".join(c.text for c in old_kids)
        new_text = "".join(c.text for c in new_kids)
        if old_text != new_text:
            edits.append(["t", list(path), old.tag, new_text])
        return True

    if len(old_kids) != len(new_kids) or any(type(a) is not type(b) for a, b in zip(old_kids, new_kids, strict=True)):
        return _replace(new, path, old.tag, edits)
    pairs = list(zip(old_kids, new_kids, strict=True))
    if any(isinstance(a, TextNode) and a != b for a, b in pairs):
        return _replace(new, path, old.tag, edits)  # text beside elements has no stable address
    element_pairs = [(a, b) for a, b in pairs if isinstance(a, Node)]
    _attr_edit(old, new, path, edits)
    return all(_diff(a, b, [*path, index], edits) for index, (a, b) in enumerate(element_pairs))


def _attrs_only(old: Node, new: Node, path: list[int], edits: list[Edit]) -> bool:
    _attr_edit(old, new, path, edits)
    return True


def _attr_edit(old: Node, new: Node, path: list[int], edits: list[Edit]) -> None:
    before, after = _attrs(old), _attrs(new)
    changes: dict[str, str | None] = {name: None for name in before if name not in after}
    changes.update({name: value for name, value in after.items() if before.get(name) != value})
    if changes:
        edits.append(["a", list(path), old.tag, changes])
