from rational import Style

WIDTH = 960  # the content column, in pixels

STICKY_HEADER = Style(position="sticky", top=0, z_index=10, background="background", border_bottom=True, padding_y="sm")
HERO = Style(padding_y="3xl")
PROSE = Style(max_width=620, line_height=1.7)
SECTION = Style(layout="vertical", gap="lg", padding_y="2xl", border_top=True)
FLAT_CARD = Style(shadow="none", gap="sm")
FOOTER = Style(padding_y="xl", border_top=True)

# Off-screen but still in the page: used for the contact form's honeypot field.
OFF_SCREEN = Style(position="absolute", left=-9999, width=1, height=1, overflow="hidden")
