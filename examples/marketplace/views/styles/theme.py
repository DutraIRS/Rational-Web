"""The brand: the ``modern`` preset with the shop's own orange, in light and dark variants."""

from rational.styling import PRESETS

THEME = PRESETS["modern"].with_colors(
    light={
        "primary": "#c2410c",
        "primary_hover": "#9a3412",
        "on_primary": "#ffffff",
        "secondary": "#fff1e6",
        "secondary_hover": "#ffe4d0",
        "on_secondary": "#9a3412",
        "focus": "#ea580c",
    },
    dark={
        "primary": "#fb923c",
        "primary_hover": "#fdba74",
        "on_primary": "#1c0a00",
        "secondary": "#3b1d0e",
        "secondary_hover": "#4a2512",
        "on_secondary": "#fed7aa",
        "focus": "#fdba74",
    },
)
