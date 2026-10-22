"""Every way to show something that is not text: images, videos, documents."""

from rational import (
    Card,
    Column,
    Grid,
    Heading,
    Image,
    Link,
    Page,
    Router,
    Style,
    Text,
    h,
)

from settings import FAVICON_CHOICES, LOGO_SVG, PDF_DOC, PHOTO_JPG, VIDEO_MP4, VIDEO_WEBM
from views.styles import GRID, PAGE

router = Router()


def EmbedCard(title: str, hint: str, *content):  # noqa: N802 - a function component
    """A titled card that explains one way to embed something, with the code under it."""
    return Card(
        Heading(title, level=3),
        Text(hint, muted=True, size="sm"),
        Column(*content, gap="md", style=Style(grow=1, min_width=0)),
        style=Style(shadow="none", padding="md", gap="sm"),
    )


@router.page("/")
class Media(Page):
    """Images, a favicon, links, a video and a PDF, each the simplest way to do it."""

    title = "Media · Rational Web"

    def render(self):
        return Column(
            Heading("Media", level=1),
            Text("Images, favicons, links, embedded documents and videos. This page needs internet.", muted=True),
            Grid(
                # -- images ----------------------------------------------------------------------
                EmbedCard(
                    "A local image",
                    "Serve your own files with app.static('/static', 'static'); the URL stays stable.",
                    Image("/static/logo.svg", alt="The Rational Web example logo"),
                    Link("Source: static/logo.svg", href="/static/logo.svg", external=True, size="sm"),
                ),
                EmbedCard(
                    "A remote image",
                    "Any public URL works. alt is required for meaningful images; "
                    'use alt="" for decorative images. Lazy loading is on by default.',
                    Image(PHOTO_JPG, alt="A stock photo of a dog", width=600, height=400),
                    Link("Source: picsum.photos", href="https://picsum.photos", external=True, size="sm"),
                ),
                EmbedCard(
                    "An SVG, sized by style",
                    "SVGs scale: set a width in the style instead of attributes.",
                    Image(LOGO_SVG, alt="The Python logo", style=Style(width=220, height="auto")),
                ),
                EmbedCard(
                    "Favicon choices",
                    "Pass any local or remote image URL as App(favicon=...). This app uses the first one.",
                    Grid(
                        *[
                            Link(
                                Image(url, alt=f"{name} favicon", width=48, height=48),
                                name,
                                href=url,
                                external=True,
                                key=name,
                            )
                            for name, url in FAVICON_CHOICES
                        ],
                        min_column_width=100,
                        gap="sm",
                    ),
                ),
                # -- links -----------------------------------------------------------------------
                EmbedCard(
                    "Links",
                    "external=True adds target=_blank and rel=noopener noreferrer. ButtonLink looks like a button.",
                    Link("python.org", href="https://www.python.org", external=True),
                    Link("A link inside the app", href="/about"),
                    Link("Mail and phone are just URLs", href="mailto:hi@example.org"),
                ),
                # -- video -------------------------------------------------------------------------
                EmbedCard(
                    "A video, with controls",
                    "h() builds any HTML element: sources, tracks, fallbacks. Multiple formats let the browser choose.",
                    h(
                        "video",
                        h("source", src=VIDEO_MP4, type="video/mp4"),
                        h("source", src=VIDEO_WEBM, type="video/webm"),
                        "Your browser cannot play this video.",
                        controls=True,
                        style=Style(width="100%", border_radius="md"),
                    ),
                ),
                # -- documents ----------------------------------------------------------------------
                EmbedCard(
                    "A PDF, inline",
                    "An iframe shows documents in the page. The same element embeds maps and other pages.",
                    h(
                        "iframe",
                        src=PDF_DOC + "#view=FitH",
                        title="An example PDF document",
                        style=Style(
                            width="100%", height=340, border_style="solid", border_width=1, border_color="border"
                        ),
                    ),
                    Link("Or link to it directly", href=PDF_DOC, external=True),
                ),
                key="cards",
                min_column_width=320,
                gap="md",
                style=GRID,
            ),
            tag="main",
            max_width=1100,
            style=PAGE,
        )


@router.page("/about")
class About(Page):
    title = "About · Rational Web"

    def render(self):
        return Column(
            Heading("About this example", level=1),
            Text("An internal link target, so the links page has somewhere to point at."),
            Link("Back to the media page", href="/"),
            tag="main",
            max_width=720,
            style=PAGE,
        )
