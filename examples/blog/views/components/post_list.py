from rational import Badge, Column, Heading, Link, Row, Text, h

from models import PostOut
from views.styles import POST_SUMMARY, TITLE_LINK


def PostMeta(post: PostOut):  # noqa: N802 - a function component
    """Date, tag links and a draft badge."""
    return Row(
        Text(f"{post.created_at:%B %d, %Y}", muted=True, size="sm", tag="span"),
        *[Link(Badge(tag), href=f"/tag/{tag}", aria_label=f"Posts tagged {tag}") for tag in post.tags],
        Badge("draft", tone="warning") if not post.published else None,
        gap="sm",
        wrap=True,
    )


def PostList(posts: list[PostOut]):  # noqa: N802
    if not posts:
        return Text("No posts yet.", muted=True)
    return Column(
        *[
            h(
                "article",
                Heading(Link(post.title, href=f"/posts/{post.slug}", style=TITLE_LINK), level=2),
                PostMeta(post),
                Text(post.summary, muted=True),
                key=post.id,
                style=POST_SUMMARY,
            )
            for post in posts
        ],
        gap="xl",
    )
