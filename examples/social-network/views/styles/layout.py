"""The look of the app: its theme and the shared styles of its layout."""

from rational import Style

THEME = "modern"
SHELL = Style(padding_y="md", background="surface", border_bottom=True)
MAIN = Style(padding_y="lg")
PANEL = Style(shadow="none", padding="md")
NARROW_SIDEBAR = Style(width=300, shrink=0, viewport={"narrow": Style(width="100%")})
