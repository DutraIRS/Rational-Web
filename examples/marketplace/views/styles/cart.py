from rational import Style

CART_PANEL = Style(grow=1, min_width=0, shadow="none")  # the lines, beside the summary on wide screens
CART_LINES = Style(margin=0, padding=0)
CART_LINE = Style(layout="horizontal", align="center", gap="md", padding_y="sm", border_bottom=True, wrap=True)
LINE_TOTAL = Style(min_width=90, text_align="right")
SUMMARY = Style(min_width=280, basis=320, align_self="start")
