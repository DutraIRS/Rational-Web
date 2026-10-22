"""The network's rules and queries. The ``@remote`` methods are also a JSON API under ``/api/social/...``.

Every list of posts is built with a fixed number of queries, however long it is: posts with
their authors (``selectinload``), like counts (one ``GROUP BY``) and your likes (one ``IN``).
"""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rational import FieldError, NotFound, RemoteError
from rational.backend import Service, remote

from models import Follow, Like, Member, MemberOut, Post, PostView, ProfileView
from settings import MAX_POST_LENGTH


class SocialService(Service):
    """Members, posts, likes and follows."""

    # -- reading ---------------------------------------------------------------------------------

    @remote(method="GET", auth="required")
    async def timeline(self, limit: int = 50) -> list[PostView]:
        """Your posts and the posts of the people you follow, newest first."""
        async with self.db.session() as db:
            me = await self._me(db)
            followees = select(Follow.followee_id).where(Follow.follower_id == me.id)
            query = _posts().where(or_(Post.author_id == me.id, Post.author_id.in_(followees)))
            return await self._views(db, list(await db.scalars(query.limit(min(limit, 100)))), me.id)

    @remote(method="GET")
    async def explore(self, limit: int = 50) -> list[PostView]:
        """Everyone's latest posts."""
        async with self.db.session() as db:
            me = await self._me(db, required=False)
            posts = list(await db.scalars(_posts().limit(min(limit, 100))))
            return await self._views(db, posts, me.id if me else None)

    @remote(method="GET")
    async def posts_by(self, handle: str, limit: int = 50) -> list[PostView]:
        """One member's posts, newest first."""
        async with self.db.session() as db:
            member = await self._member(db, handle)
            me = await self._me(db, required=False)
            posts = list(await db.scalars(_posts().where(Post.author_id == member.id).limit(min(limit, 100))))
            return await self._views(db, posts, me.id if me else None)

    @remote(method="GET")
    async def profile(self, handle: str) -> ProfileView:
        """A member's profile with follower counts."""
        async with self.db.session() as db:
            member = await self._member(db, handle)
            me = await self._me(db, required=False)
            return await self._profile(db, member, me)

    @remote(method="GET")
    async def members(self) -> list[MemberOut]:
        """Everyone, by handle."""
        async with self.db.session() as db:
            return [MemberOut.model_validate(m) for m in await db.scalars(select(Member).order_by(Member.handle))]

    @remote(method="GET", auth="required")
    async def suggestions(self, limit: int = 4) -> list[MemberOut]:
        """People you don't follow yet."""
        async with self.db.session() as db:
            me = await self._me(db)
            followed = select(Follow.followee_id).where(Follow.follower_id == me.id)
            query = select(Member).where(Member.id != me.id, Member.id.not_in(followed)).order_by(Member.handle)
            return [MemberOut.model_validate(m) for m in await db.scalars(query.limit(limit))]

    # -- writing ---------------------------------------------------------------------------------

    async def join(self, handle: str, name: str) -> MemberOut:
        async with self.db.transaction() as db:
            if await db.scalar(select(Member.id).where(Member.handle == handle)) is not None:
                raise FieldError("handle", "That handle is taken")
            member = Member(handle=handle, name=name.strip())
            db.add(member)
            await db.flush()
            return MemberOut.model_validate(member)

    @remote(auth="required")
    async def publish(self, body: str) -> PostView:
        """Post something (up to 280 characters)."""
        body = body.strip()
        if not body or len(body) > MAX_POST_LENGTH:
            raise FieldError("body", f"Posts are 1 to {MAX_POST_LENGTH} characters")
        async with self.db.transaction() as db:
            me = await self._me(db)
            post = Post(author_id=me.id, body=body, author=me)
            db.add(post)
            await db.flush()
            return (await self._views(db, [post], me.id))[0]

    @remote(auth="required")
    async def toggle_like(self, post_id: int) -> PostView:
        """Like a post, or take your like back."""
        async with self.db.transaction() as db:
            me = await self._me(db)
            post = await db.scalar(_posts().where(Post.id == post_id))
            if post is None:
                raise NotFound("No such post")
            like = await db.get(Like, (me.id, post_id))
            if like is None:
                db.add(Like(member_id=me.id, post_id=post_id))
            else:
                await db.delete(like)
            await db.flush()
            return (await self._views(db, [post], me.id))[0]

    @remote(auth="required")
    async def toggle_follow(self, handle: str) -> ProfileView:
        """Follow a member, or stop following them."""
        async with self.db.transaction() as db:
            me = await self._me(db)
            member = await self._member(db, handle)
            if member.id == me.id:
                raise RemoteError("You can't follow yourself")
            follow = await db.get(Follow, (me.id, member.id))
            if follow is None:
                db.add(Follow(follower_id=me.id, followee_id=member.id))
            else:
                await db.delete(follow)
            await db.flush()
            return await self._profile(db, member, me)

    # -- helpers ---------------------------------------------------------------------------------

    async def _me(self, db: AsyncSession, *, required: bool = True) -> Member | None:
        me = await db.scalar(select(Member).where(Member.handle == self.user)) if self.user else None
        if me is None and required:
            raise RemoteError("Please sign in again", status=401)
        return me

    async def _member(self, db: AsyncSession, handle: str) -> Member:
        member = await db.scalar(select(Member).where(Member.handle == handle.lower()))
        if member is None:
            raise NotFound(f"No member called @{handle}")
        return member

    async def _views(self, db: AsyncSession, posts: list[Post], me_id: int | None) -> list[PostView]:
        ids = [p.id for p in posts]
        like_counts = select(Like.post_id, func.count()).where(Like.post_id.in_(ids)).group_by(Like.post_id)
        counts = dict((await db.execute(like_counts)).all())
        liked = set()
        if me_id is not None:
            liked = set(await db.scalars(select(Like.post_id).where(Like.member_id == me_id, Like.post_id.in_(ids))))
        return [
            PostView(
                id=p.id,
                body=p.body,
                created_at=p.created_at,
                author_handle=p.author.handle,
                author_name=p.author.name,
                likes=counts.get(p.id, 0),
                liked=p.id in liked,
            )
            for p in posts
        ]

    async def _profile(self, db: AsyncSession, member: Member, me: Member | None) -> ProfileView:
        def count(model, column):
            return db.scalar(select(func.count()).select_from(model).where(column == member.id))

        return ProfileView(
            handle=member.handle,
            name=member.name,
            bio=member.bio,
            posts=await count(Post, Post.author_id),
            followers=await count(Follow, Follow.followee_id),
            following=await count(Follow, Follow.follower_id),
            followed_by_me=me is not None and await db.get(Follow, (me.id, member.id)) is not None,
            is_me=me is not None and me.id == member.id,
        )


def _posts():
    """Newest posts first, with their authors loaded in one extra query."""
    return select(Post).options(selectinload(Post.author)).order_by(Post.created_at.desc(), Post.id.desc())
