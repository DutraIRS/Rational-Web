"""A vertical timeline drawn with plain styles: a line on the left and a dot per job."""

from rational import Style

TIMELINE = Style(
    layout="vertical",
    gap="xl",
    margin=0,
    padding_left="lg",
    border_left="2px solid var(--rw-color-border)",
)
JOB = Style(position="relative", layout="vertical", gap="sm", list_style="none")
DOT = Style(
    position="absolute",
    left=-31,
    top=6,
    width=12,
    height=12,
    border_radius="full",
    background="primary",
    raw={"box-shadow": "0 0 0 4px var(--rw-color-background)"},
)
