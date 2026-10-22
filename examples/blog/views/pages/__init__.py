"""Every page of the blog, combined into one router for ``app.py``.

``feed_router`` serves ``/feed.xml``: not every URL needs a ``Page``. It is a plain FastAPI router.
"""

from rational import Router

from . import admin, feed, public

router = Router()
router.include(public.router)
router.include(admin.router)

feed_router = feed.router
