"""The look of the app: its theme and the shared ``Style`` values that components and pages use."""

from rational import Style

THEME = "modern"  # a preset: modern, minimal, soft or professional

PAGE = Style(layout="vertical", gap="lg", padding_y="xl")
COUNT = Style(font_size="3xl", font_weight=700)
