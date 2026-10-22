"""Turning post text into nodes. Everything goes through escaped nodes, so it is safe by construction."""

import re

from rational import Heading, Text, h

from views.styles import BULLETS, PROSE


def render_body(text: str) -> list:
    """A tiny Markdown subset: ``## heading``, ``### heading``, ``- list`` items and paragraphs."""
    blocks = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if lines[0].startswith("### "):
            blocks.append(Heading(lines[0][4:], level=3))
        elif lines[0].startswith("## "):
            blocks.append(Heading(lines[0][3:], level=2))
        elif all(line.startswith("- ") for line in lines):
            blocks.append(h("ul", *[h("li", line[2:]) for line in lines], style=BULLETS))
        else:
            blocks.append(Text(" ".join(lines), style=PROSE))
    return blocks
