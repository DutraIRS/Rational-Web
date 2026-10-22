"""Tables and charts, drawn with plain styles."""

from rational import Style

# Tables scroll sideways on small screens instead of breaking the layout.
SCROLL_X = Style(overflow_x="auto")
TABLE = Style(width="100%", raw={"border-collapse": "collapse"})
CELL = Style(padding_y="sm", padding_x="sm", text_align="left", border_bottom=True, white_space="nowrap")
HEADER_CELL = CELL | Style(font_size="sm", color="muted")

# The chart's card is a *container*: AMOUNT hides when the card itself is narrow (a container query).
CHART = Style(container_type="inline-size")
CHART_LIST = Style(layout="vertical", gap="sm", padding=0, margin=0)
BAR_ROW = Style(layout="horizontal", align="center", gap="sm")
BAR_LABEL = Style(width=72, shrink=0)
BAR_TRACK = Style(grow=1, background="surface_alt", border_radius="full")
BAR = Style(height=12, border_radius="full", background="primary")  # its width is set per bar
AMOUNT = Style(width=96, text_align="right", container={"compact": Style(display="none")})
