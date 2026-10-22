from rational import Column, Container

from .header import ShopHeader
from views.styles import MAIN


def Shell(*content):  # noqa: N802 - a function component
    """The header and the main column around a page's content."""
    return Column(ShopHeader(), Container(*content, tag="main", max_width=1080, style=MAIN), gap=0)
