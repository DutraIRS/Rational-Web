# Social network

A small social network called *Murmur*: posts, likes, follows, profiles and a home timeline.

```
social-network/
├── app.py                    # composition root
└── social/
    ├── config.py             # settings (DATABASE_URL, 280-character limit)
    ├── db.py                 # engine + declarative base
    ├── models.py             # Member, Post, Follow, Like
    ├── schemas.py            # PostView, ProfileView, forms
    ├── timefmt.py            # "5m", "3h", "2d"
    ├── seed.py               # demo members, follows, posts and likes
    ├── services.py           # SocialService: queries without N+1 (+ JSON API)
    ├── components/
    │   ├── shell.py          # header, navigation, account menu
    │   ├── composer.py       # write a post, with a live character count
    │   ├── post_card.py      # one post with its like button; PostList
    │   └── who_to_follow.py  # suggestions
    └── pages/
        ├── home.py           # / : your timeline (signed-in only)
        ├── explore.py        # /explore : everyone's posts (public)
        ├── profile.py        # /u/{handle} : profile, stats, follow button
        └── account.py        # /login : demo accounts or join
```

## What it shows

- **Relational data done right:** association tables with composite keys, `lazy="raise"` relationships,
  and lists of posts built with a fixed number of queries (authors via `selectinload`, like counts via
  one `GROUP BY`, your likes via one `IN`), however many posts there are.
- **Local updates:** liking re-renders only that post's card. Its state starts from the props and then
  follows the server's answer.
- **Callback props between components:** the composer and "who to follow" tell the page to reload the
  timeline (`posted=`, `followed=`).
- **A live character counter:** debounced `on_input` drives the count and enables the Post button; the
  server validates again on submit.
- **Public and private pages side by side:** `/explore` and profiles are public, likes and follows need
  a member, and `/` redirects to sign-in.
- **Responsive two-column layout:** suggestions sit beside the timeline and drop below it on narrow screens.

## Run it

```console
$ pip install "rational[db]"
$ cd examples/social-network
$ python app.py --dev
```

Continue as `@ada`, like a few posts, follow `@edsger`, and watch your timeline change.
