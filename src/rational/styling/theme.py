"""Themes: semantic design tokens compiled to CSS custom properties."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

ThemeMode = Literal["light", "dark", "system"]

COLOR_TOKENS = (
    "primary",
    "primary_hover",
    "on_primary",
    "secondary",
    "secondary_hover",
    "on_secondary",
    "background",
    "on_background",
    "surface",
    "surface_alt",
    "on_surface",
    "border",
    "muted",
    "danger",
    "danger_hover",
    "on_danger",
    "success",
    "warning",
    "focus",
)

SPACE = {"none": "0", "xs": "4px", "sm": "8px", "md": "16px", "lg": "24px", "xl": "32px", "2xl": "48px", "3xl": "64px"}
RADIUS = {"none": "0", "sm": "4px", "md": "8px", "lg": "12px", "xl": "20px", "full": "9999px"}
FONT_SIZE = {
    "xs": "0.75rem",
    "sm": "0.875rem",
    "md": "1rem",
    "lg": "1.125rem",
    "xl": "1.375rem",
    "2xl": "1.75rem",
    "3xl": "2.25rem",
    "4xl": "3rem",
}
FONTS = {
    "body": 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    "heading": "inherit",
    "mono": 'ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace',
}
SHADOWS = {
    "none": "none",
    "sm": "0 1px 2px rgb(0 0 0 / 0.06)",
    "md": "0 2px 8px rgb(0 0 0 / 0.08), 0 1px 2px rgb(0 0 0 / 0.04)",
    "lg": "0 12px 32px rgb(0 0 0 / 0.12), 0 2px 6px rgb(0 0 0 / 0.06)",
}


@dataclass(frozen=True)
class Theme:
    name: str
    light: Mapping[str, str]
    dark: Mapping[str, str]
    space: Mapping[str, str] = field(default_factory=lambda: dict(SPACE))
    radius: Mapping[str, str] = field(default_factory=lambda: dict(RADIUS))
    font_size: Mapping[str, str] = field(default_factory=lambda: dict(FONT_SIZE))
    fonts: Mapping[str, str] = field(default_factory=lambda: dict(FONTS))
    shadows: Mapping[str, str] = field(default_factory=lambda: dict(SHADOWS))
    motion: str = "160ms"
    density: float = 1.0

    def __post_init__(self) -> None:
        for mode in ("light", "dark"):
            missing = set(COLOR_TOKENS) - set(getattr(self, mode))
            if missing:
                raise ValueError(f"theme {self.name!r} ({mode}) is missing colors: {sorted(missing)}")

    def with_colors(self, *, light: Mapping[str, str] | None = None, dark: Mapping[str, str] | None = None) -> Theme:
        """Return a copy with some color tokens overridden (or new ones added)."""
        return replace(self, light={**self.light, **(light or {})}, dark={**self.dark, **(dark or {})})

    @property
    def color_names(self) -> frozenset[str]:
        return frozenset(self.light) | frozenset(self.dark)

    def css(self, mode: ThemeMode = "system") -> str:
        def colors(values: Mapping[str, str]) -> str:
            return "".join(f"--rw-color-{_dash(k)}:{v};" for k, v in values.items())

        scales = "".join(
            [f"--rw-space-{k}:{_scale(v, self.density)};" for k, v in self.space.items()]
            + [f"--rw-radius-{k}:{v};" for k, v in self.radius.items()]
            + [f"--rw-font-size-{k}:{v};" for k, v in self.font_size.items()]
            + [f"--rw-font-{k}:{v};" for k, v in self.fonts.items()]
            + [f"--rw-shadow-{k}:{v};" for k, v in self.shadows.items()]
            + [f"--rw-motion:{self.motion};"]
        )
        light, dark = colors(self.light), colors(self.dark)
        parts = [f":root{{{scales}{light}color-scheme:light;}}"]
        if mode == "system":
            parts.append(
                f"@media (prefers-color-scheme: dark){{:root:not([data-theme=light]){{{dark}color-scheme:dark;}}}}"
            )
        parts.append(f":root[data-theme=dark]{{{dark}color-scheme:dark;}}")
        parts.append(f":root[data-theme=light]{{{light}color-scheme:light;}}")
        return "".join(parts) + BASE_CSS


def _dash(name: str) -> str:
    return name.replace("_", "-")


def _scale(value: str, density: float) -> str:
    if density == 1.0 or not value.endswith("px"):
        return value
    return f"{round(float(value[:-2]) * density, 2):g}px"


BASE_CSS = (
    "*,*::before,*::after{box-sizing:border-box}"
    "html{-webkit-text-size-adjust:100%;text-size-adjust:100%}"
    "body{margin:0;min-height:100vh;font-family:var(--rw-font-body);font-size:var(--rw-font-size-md);"
    "line-height:1.55;background:var(--rw-color-background);color:var(--rw-color-on-background);"
    "-webkit-font-smoothing:antialiased}"
    "h1,h2,h3,h4,h5,h6{font-family:var(--rw-font-heading);line-height:1.2;margin:0}"
    "p{margin:0}"
    "img,svg,video{display:block;max-width:100%;height:auto}"
    "button,input,select,textarea{font:inherit;color:inherit}"
    "a{color:var(--rw-color-primary)}"
    ":focus-visible{outline:2px solid var(--rw-color-focus);outline-offset:2px}"
    "[hidden]{display:none!important}"
    "[aria-invalid=true]{border-color:var(--rw-color-danger)!important}"
    ".rw-sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;"
    "clip:rect(0,0,0,0);white-space:nowrap;border:0}"
    "[aria-busy=true]{cursor:progress}"
    "html[data-rw-busy]::before{content:'';position:fixed;top:0;left:0;right:0;height:3px;z-index:2147483647;"
    "background:var(--rw-color-primary);transform-origin:left;opacity:0;"
    "animation:rw-progress 1.2s ease-in-out .15s infinite}"
    "@keyframes rw-progress{from{transform:scaleX(0);opacity:1}to{transform:scaleX(1);opacity:1}}"
    ".rw-skeleton{background:linear-gradient(90deg,var(--rw-color-surface-alt) 25%,var(--rw-color-border) 50%,"
    "var(--rw-color-surface-alt) 75%);background-size:200% 100%;border-radius:6px;"
    "animation:rw-shimmer 1.4s linear infinite}"
    "@keyframes rw-shimmer{from{background-position:200% 0}to{background-position:-200% 0}}"
    "[role=tab][aria-selected=true]{border-bottom-color:var(--rw-color-primary)!important;"
    "color:var(--rw-color-primary)!important}"
    "dialog::backdrop{background:rgba(0,0,0,.5)}"
    "@media (prefers-reduced-motion: reduce){*,*::before,*::after{animation-duration:0.01ms!important;"
    "animation-iteration-count:1!important;transition-duration:0.01ms!important;scroll-behavior:auto!important}}"
)


MODERN = Theme(
    name="modern",
    light={
        "primary": "#4f46e5",
        "primary_hover": "#4338ca",
        "on_primary": "#ffffff",
        "secondary": "#eef2ff",
        "secondary_hover": "#e0e7ff",
        "on_secondary": "#3730a3",
        "background": "#f8fafc",
        "on_background": "#0f172a",
        "surface": "#ffffff",
        "surface_alt": "#f1f5f9",
        "on_surface": "#0f172a",
        "border": "#e2e8f0",
        "muted": "#64748b",
        "danger": "#dc2626",
        "danger_hover": "#b91c1c",
        "on_danger": "#ffffff",
        "success": "#16a34a",
        "warning": "#d97706",
        "focus": "#6366f1",
    },
    dark={
        "primary": "#818cf8",
        "primary_hover": "#a5b4fc",
        "on_primary": "#0b1020",
        "secondary": "#1e1b4b",
        "secondary_hover": "#312e81",
        "on_secondary": "#c7d2fe",
        "background": "#0b1020",
        "on_background": "#e2e8f0",
        "surface": "#131a2e",
        "surface_alt": "#1a2238",
        "on_surface": "#e2e8f0",
        "border": "#26304a",
        "muted": "#94a3b8",
        "danger": "#f87171",
        "danger_hover": "#fca5a5",
        "on_danger": "#1a0505",
        "success": "#4ade80",
        "warning": "#fbbf24",
        "focus": "#a5b4fc",
    },
)

MINIMAL = Theme(
    name="minimal",
    light={
        "primary": "#111111",
        "primary_hover": "#333333",
        "on_primary": "#ffffff",
        "secondary": "#f2f2f2",
        "secondary_hover": "#e6e6e6",
        "on_secondary": "#111111",
        "background": "#ffffff",
        "on_background": "#111111",
        "surface": "#ffffff",
        "surface_alt": "#f7f7f7",
        "on_surface": "#111111",
        "border": "#e5e5e5",
        "muted": "#6b6b6b",
        "danger": "#c62828",
        "danger_hover": "#a31f1f",
        "on_danger": "#ffffff",
        "success": "#2e7d32",
        "warning": "#b26a00",
        "focus": "#111111",
    },
    dark={
        "primary": "#f5f5f5",
        "primary_hover": "#d4d4d4",
        "on_primary": "#111111",
        "secondary": "#1f1f1f",
        "secondary_hover": "#2a2a2a",
        "on_secondary": "#f5f5f5",
        "background": "#0d0d0d",
        "on_background": "#ededed",
        "surface": "#141414",
        "surface_alt": "#1b1b1b",
        "on_surface": "#ededed",
        "border": "#2a2a2a",
        "muted": "#9a9a9a",
        "danger": "#ef5350",
        "danger_hover": "#e57373",
        "on_danger": "#111111",
        "success": "#66bb6a",
        "warning": "#ffb74d",
        "focus": "#f5f5f5",
    },
    radius={**RADIUS, "sm": "2px", "md": "4px", "lg": "6px", "xl": "10px"},
    shadows={**SHADOWS, "sm": "none", "md": "none", "lg": "0 8px 24px rgb(0 0 0 / 0.08)"},
)

SOFT = Theme(
    name="soft",
    light={
        "primary": "#0d9488",
        "primary_hover": "#0f766e",
        "on_primary": "#ffffff",
        "secondary": "#e6f4f1",
        "secondary_hover": "#d3ece7",
        "on_secondary": "#115e59",
        "background": "#fbf8f4",
        "on_background": "#292524",
        "surface": "#ffffff",
        "surface_alt": "#f5f0ea",
        "on_surface": "#292524",
        "border": "#ebe3d9",
        "muted": "#78716c",
        "danger": "#e11d48",
        "danger_hover": "#be123c",
        "on_danger": "#ffffff",
        "success": "#059669",
        "warning": "#d97706",
        "focus": "#14b8a6",
    },
    dark={
        "primary": "#2dd4bf",
        "primary_hover": "#5eead4",
        "on_primary": "#042f2e",
        "secondary": "#123a37",
        "secondary_hover": "#17504b",
        "on_secondary": "#99f6e4",
        "background": "#1c1917",
        "on_background": "#e7e5e4",
        "surface": "#262220",
        "surface_alt": "#2e2926",
        "on_surface": "#e7e5e4",
        "border": "#3a3431",
        "muted": "#a8a29e",
        "danger": "#fb7185",
        "danger_hover": "#fda4af",
        "on_danger": "#1c0a10",
        "success": "#34d399",
        "warning": "#fbbf24",
        "focus": "#5eead4",
    },
    radius={**RADIUS, "sm": "8px", "md": "14px", "lg": "20px", "xl": "28px"},
)

PROFESSIONAL = Theme(
    name="professional",
    light={
        "primary": "#1d4ed8",
        "primary_hover": "#1e40af",
        "on_primary": "#ffffff",
        "secondary": "#e8eef8",
        "secondary_hover": "#d7e1f2",
        "on_secondary": "#1e3a8a",
        "background": "#f4f6f9",
        "on_background": "#111827",
        "surface": "#ffffff",
        "surface_alt": "#f0f2f5",
        "on_surface": "#111827",
        "border": "#d8dde5",
        "muted": "#5b6474",
        "danger": "#b91c1c",
        "danger_hover": "#991b1b",
        "on_danger": "#ffffff",
        "success": "#15803d",
        "warning": "#b45309",
        "focus": "#2563eb",
    },
    dark={
        "primary": "#60a5fa",
        "primary_hover": "#93c5fd",
        "on_primary": "#081225",
        "secondary": "#16243d",
        "secondary_hover": "#1e3254",
        "on_secondary": "#bfdbfe",
        "background": "#0d131c",
        "on_background": "#e5e7eb",
        "surface": "#141b26",
        "surface_alt": "#1a2330",
        "on_surface": "#e5e7eb",
        "border": "#273244",
        "muted": "#9ca3af",
        "danger": "#f87171",
        "danger_hover": "#fca5a5",
        "on_danger": "#1f0707",
        "success": "#4ade80",
        "warning": "#fbbf24",
        "focus": "#93c5fd",
    },
    radius={**RADIUS, "sm": "3px", "md": "6px", "lg": "8px", "xl": "12px"},
    density=0.9,
)

PRESETS: dict[str, Theme] = {t.name: t for t in (MODERN, MINIMAL, SOFT, PROFESSIONAL)}


def get_theme(theme: str | Theme) -> Theme:
    if isinstance(theme, Theme):
        return theme
    try:
        return PRESETS[theme]
    except KeyError:
        raise ValueError(f"unknown theme {theme!r}; presets: {sorted(PRESETS)}") from None
