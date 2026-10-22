"""Every page of the app, combined into one router for ``app.py``."""

from rational import Router

from . import overview

router = Router()
router.include(overview.router)
