from rational import Heading
from rational import Section as SectionElement

from views.styles import SECTION


def Section(anchor: str, title: str, *content):  # noqa: N802 - a function component
    """A titled section the header navigation can jump to (``#anchor``)."""
    return SectionElement(Heading(title, level=2), *content, id=anchor, aria_label=title, style=SECTION)
