from rational import Style

SEARCH = Style(grow=1, min_width=200)
PRODUCT_CARD = Style(height="100%", gap="sm")

# The product "photo": a big emoji on a tinted tile.
PRODUCT_TILE = Style(
    font_size="4xl",
    text_align="center",
    padding_y="lg",
    border_radius="md",
    background="surface_alt",
    raw={"line-height": "1"},
)
PRODUCT_TILE_LARGE = PRODUCT_TILE | Style(padding="xl", border_radius="lg")
