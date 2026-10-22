"""Text, headings, buttons, links and images."""

from __future__ import annotations

from typing import Any, Literal

from ..rendering.builder import EventValue, h
from ..rendering.nodes import Node
from ..styling.style import Style, merge

ButtonVariant = Literal["primary", "secondary", "outline", "ghost", "danger"]
Size = Literal["sm", "md", "lg"]

TEXT = Style(margin=0)
HEADING_STYLES = {
    1: Style(font_size="3xl", font_weight=750, letter_spacing="-0.02em"),
    2: Style(font_size="2xl", font_weight=700, letter_spacing="-0.01em"),
    3: Style(font_size="xl", font_weight=650),
    4: Style(font_size="lg", font_weight=600),
    5: Style(font_size="md", font_weight=600),
    6: Style(font_size="sm", font_weight=600, text_transform="uppercase", letter_spacing="0.04em"),
}

BUTTON = Style(
    display="inline-flex",
    width="fit-content",  # never stretched by a flex column; full_width=True opts in
    align="center",
    justify="center",
    gap="sm",
    border="1px solid transparent",
    border_radius="md",
    font_weight=600,
    line_height=1.2,
    cursor="pointer",
    transition=True,
    user_select="none",
    white_space="nowrap",
    text_decoration="none",
    active=Style(transform="translateY(1px)"),
    disabled=Style(opacity=0.55, cursor="not-allowed", transform="none"),
)
BUTTON_VARIANTS: dict[str, Style] = {
    "primary": Style(background="primary", color="on_primary", hover=Style(background="primary_hover")),
    "secondary": Style(background="secondary", color="on_secondary", hover=Style(background="secondary_hover")),
    "outline": Style(background="transparent", color="on_surface", border=True, hover=Style(background="surface_alt")),
    "ghost": Style(background="transparent", color="on_surface", hover=Style(background="surface_alt")),
    "danger": Style(background="danger", color="on_danger", hover=Style(background="danger_hover")),
}
BUTTON_SIZES: dict[str, Style] = {
    "sm": Style(padding_y=6, padding_x=12, font_size="sm"),
    "md": Style(padding_y=10, padding_x=18, font_size="sm"),
    "lg": Style(padding_y=13, padding_x=24, font_size="md"),
}
LINK = Style(
    color="primary",
    raw={"text-underline-offset": "3px"},
    hover=Style(text_decoration="underline"),
    text_decoration="none",
)
IMAGE = Style(max_width="100%", height="auto")


def button_style(
    variant: ButtonVariant = "primary", size: Size = "md", *, full_width: bool = False, style: Style | None = None
) -> Style:
    """The composed button look, shared by ``Button`` and ``ButtonLink``."""
    if variant not in BUTTON_VARIANTS:
        raise ValueError(f"unknown button variant {variant!r}; use one of {sorted(BUTTON_VARIANTS)}")
    return (
        BUTTON | BUTTON_VARIANTS[variant] | BUTTON_SIZES[size] | (Style(width="100%") if full_width else None) | style
    )


def Text(  # noqa: N802 - primitives are capitalized like components
    *content: Any,
    tag: Literal["p", "span", "div", "small", "strong", "em", "label"] = "p",
    size: str | None = None,
    weight: int | str | None = None,
    color: str | None = None,
    muted: bool = False,
    align: str | None = None,
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    """A run of text. ``content`` may include callables, evaluated now."""
    own = Style(font_size=size, font_weight=weight, color="muted" if muted else color, text_align=align)
    return h(tag, *content, key=key, style=merge(TEXT, own, style), **attrs)


def Heading(  # noqa: N802
    *content: Any,
    level: Literal[1, 2, 3, 4, 5, 6] = 2,
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    if level not in HEADING_STYLES:
        raise ValueError("heading level must be 1-6")
    return h(f"h{level}", *content, key=key, style=merge(HEADING_STYLES[level], style), **attrs)


def Button(  # noqa: N802
    *content: Any,
    on_click: EventValue = None,
    variant: ButtonVariant = "primary",
    size: Size = "md",
    type: Literal["button", "submit", "reset"] = "button",  # noqa: A002
    disabled: bool = False,
    full_width: bool = False,
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    return h(
        "button",
        *content,
        key=key,
        style=button_style(variant, size, full_width=full_width, style=style),
        type=type,
        disabled=disabled,
        on_click=on_click,
        **attrs,
    )


def Link(  # noqa: N802
    *content: Any,
    href: str,
    external: bool = False,
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    if external:
        attrs.setdefault("target", "_blank")
        attrs.setdefault("rel", "noopener noreferrer")
    return h("a", *content, href=href, key=key, style=merge(LINK, style), **attrs)


def ButtonLink(  # noqa: N802
    *content: Any,
    href: str,
    variant: ButtonVariant = "primary",
    size: Size = "md",
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    """A link that looks like a button (navigation, not an action)."""
    return h("a", *content, href=href, key=key, style=button_style(variant, size, style=style), **attrs)


def Image(  # noqa: N802
    src: str,
    *,
    alt: str,
    width: int | None = None,
    height: int | None = None,
    lazy: bool = True,
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    """``alt`` is required; pass ``alt=""`` for purely decorative images."""
    return h(
        "img",
        src=src,
        alt=alt,
        width=width,
        height=height,
        loading="lazy" if lazy else None,
        decoding="async",
        key=key,
        style=merge(IMAGE, style),
        **attrs,
    )


BADGE = Style(
    display="inline-flex",
    width="fit-content",  # a label, not a bar: never stretched by a flex column
    align="center",
    gap=4,
    padding_y=2,
    padding_x=8,
    border_radius="full",
    font_size="xs",
    font_weight=600,
    line_height=1.6,
    white_space="nowrap",
)
BADGE_TONES: dict[str, Style] = {
    "neutral": Style(background="surface_alt", color="on_surface"),
    "primary": Style(background="secondary", color="on_secondary"),
    **{
        tone: Style(background=f"color-mix(in srgb, var(--rw-color-{tone}) 16%, transparent)", color=tone)
        for tone in ("success", "warning", "danger")
    },
}

Tone = Literal["neutral", "primary", "success", "warning", "danger"]


def Badge(  # noqa: N802
    *content: Any,
    tone: Tone = "neutral",
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    """A small label for statuses, tags, categories or counts."""
    if tone not in BADGE_TONES:
        raise ValueError(f"unknown badge tone {tone!r}; use one of {sorted(BADGE_TONES)}")
    return h("span", *content, key=key, style=merge(BADGE, BADGE_TONES[tone], style), **attrs)


def Avatar(  # noqa: N802
    name: str,
    *,
    size: int = 40,
    src: str | None = None,
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    """A round picture, or the person's initials when there is no ``src``."""
    box = Style(
        width=size,
        height=size,
        border_radius="full",
        shrink=0,
        display="inline-flex",
        align="center",
        justify="center",
        overflow="hidden",
        background="secondary",
        color="on_secondary",
        font_weight=700,
        font_size=f"{max(size * 0.4, 10):g}px",
        user_select="none",
    )
    if src:
        return h("img", src=src, alt=name, width=size, height=size, key=key,
                 style=merge(box, Style(object_fit="cover"), style), **attrs)  # fmt: skip
    initials = "".join(part[0] for part in name.split()[:2]).upper() or "?"
    return h("span", initials, role="img", aria_label=name, key=key, style=merge(box, style), **attrs)
