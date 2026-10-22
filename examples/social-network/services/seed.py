"""Demo members, follows, posts and likes, inserted on the first start."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from models import Follow, Like, Member, Post
from models.database import database

MEMBERS = [
    ("ada", "Ada Lovelace", "Poet of numbers. Notes on engines."),
    ("grace", "Grace Hopper", "Compilers, nanoseconds and naval stories."),
    ("alan", "Alan Turing", "Machines, morphogenesis and long runs."),
    ("margaret", "Margaret Hamilton", "Software engineering, before it had a name."),
    ("edsger", "Edsger Dijkstra", "Simplicity is prerequisite for reliability."),
]
FOLLOWS = [
    ("ada", "grace"),
    ("ada", "alan"),
    ("grace", "ada"),
    ("grace", "margaret"),
    ("alan", "ada"),
    ("margaret", "grace"),
    ("edsger", "alan"),
]
POSTS = [  # handle, minutes ago, text
    ("grace", 4, "A nanosecond is about 30 cm of wire. Keep your functions short, too."),
    ("ada", 18, "The engine weaves algebraic patterns just as the loom weaves flowers and leaves."),
    ("margaret", 45, "Write the error handling first. The happy path can wait."),
    ("alan", 90, "Can machines think? Today's question: can they render HTML on the server?"),
    ("edsger", 150, "If debugging is removing bugs, programming must be putting them in."),
    ("ada", 300, "Imagination is the discovering faculty, pre-eminently."),
    ("grace", 720, "The most dangerous phrase: 'we've always done it this way.'"),
    ("margaret", 1440, "There is no such thing as a small change to a flight program."),
]
LIKES = [("ada", 0), ("alan", 0), ("margaret", 0), ("grace", 1), ("alan", 1), ("grace", 2), ("ada", 3)]


async def seed_network() -> None:
    async with database.transaction() as db:
        if await db.scalar(select(Member.id).limit(1)) is not None:
            return  # only on an empty database
        members = {handle: Member(handle=handle, name=name, bio=bio) for handle, name, bio in MEMBERS}
        db.add_all(members.values())
        await db.flush()
        db.add_all(Follow(follower_id=members[a].id, followee_id=members[b].id) for a, b in FOLLOWS)
        now = datetime.now(UTC)
        posts = [
            Post(author_id=members[h].id, body=text, created_at=now - timedelta(minutes=minutes))
            for h, minutes, text in POSTS
        ]
        db.add_all(posts)
        await db.flush()
        db.add_all(Like(member_id=members[h].id, post_id=posts[i].id) for h, i in LIKES)
