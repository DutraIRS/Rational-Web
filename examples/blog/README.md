# Blog

A blog with fast public pages, comments, an editor with live preview, an RSS feed and a JSON API.

```
blog/
├── app.py                  # composition root: App, pages, service, feed, startup hooks
├── settings.py             # settings from the environment (DATABASE_URL, BLOG_PASSWORD)
├── models/
│   ├── database.py         # engine + declarative base
│   ├── post.py             # the Post table, PostOut, PostIn
│   ├── comment.py          # the Comment table, CommentOut, CommentIn
│   └── account.py          # the admin sign-in form
├── services/
│   ├── blog.py             # BlogService: drafts, slugs, admin rules (+ JSON API)
│   └── seed.py             # demo posts on the first start
└── views/
    ├── styles/
    │   ├── theme.py        # the theme preset
    │   ├── layout.py       # reading width, header, footer
    │   ├── article.py      # posts, lists and comments
    │   └── editor.py       # the editor's two columns
    ├── components/
    │   ├── shell.py        # header, main column, footer (a function component)
    │   ├── post_list.py    # PostMeta, PostList
    │   ├── markup.py       # a tiny, safe Markdown subset
    │   ├── comments.py     # the comment thread and form
    │   └── editor.py       # form + live preview
    └── pages/
        ├── public.py       # /, /tag/{tag}, /posts/{slug}
        ├── admin.py        # /login, /admin, /admin/posts/new, /admin/posts/{post_id}
        └── feed.py         # /feed.xml, a plain FastAPI router (the escape hatch)
```

## What it shows

- **Zero-JavaScript pages:** the index and tag pages have no event handlers, so the browser gets
  HTML and CSS only. Post pages load the small runtime just for the comment form.
- **Typed path parameters:** `/posts/{slug}`, `/tag/{tag}`, `/admin/posts/{post_id}` (an `int`);
  unknown slugs and drafts are a 404 for readers.
- **Safe rich text:** `markup.py` turns a Markdown subset into escaped nodes, so it is safe by construction.
- **Live preview:** the editor re-renders the preview as you type, with the same code as the public page.
- **Function components:** `Shell`, `PostMeta` and `PostList` are plain functions returning nodes.
- **The escape hatch:** `/feed.xml` is an ordinary FastAPI `APIRouter`.
- **One service, two interfaces:** `BlogService` powers the pages and the public JSON API (`/api/docs`).

## Run it

```console
$ pip install "rational[db]"
$ cd examples/blog
$ python app.py --dev
```

Sign in at http://127.0.0.1:8000/login with the password `rational` (set `BLOG_PASSWORD` to change it).
