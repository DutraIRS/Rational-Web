"""The page frame. The ``narrow`` breakpoint is "below 1024px": tablets and phones."""

from rational import Style

SIDEBAR = Style(
    layout="vertical",
    gap="md",
    padding="lg",
    min_width=220,
    background="surface",
    border_right=True,
    min_height="100vh",
    viewport={"narrow": Style(min_height="auto", border_right=False, border_bottom=True)},
)
NAV_LIST = Style(viewport={"narrow": Style(layout="horizontal", wrap=True)})  # a compact row on phones
NAV_LINK = Style(
    padding_y="xs",
    padding_x="sm",
    border_radius="md",
    color="on_surface",
    hover=Style(background="surface_alt", text_decoration="none"),
)
MAIN = Style(
    layout="vertical",
    gap="lg",
    padding="xl",
    grow=1,
    min_width=0,
    viewport={"mobile": Style(padding="md")},
)
