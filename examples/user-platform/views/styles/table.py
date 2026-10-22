from rational import Style

SCROLL_X = Style(overflow_x="auto")  # wide tables scroll instead of breaking the layout
TABLE = Style(width="100%", raw={"border-collapse": "collapse"})
CELL = Style(padding_y="sm", padding_x="sm", border_bottom=True, text_align="left")
