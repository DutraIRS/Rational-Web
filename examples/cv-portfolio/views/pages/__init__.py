"""Every page of the site, combined into one router for ``app.py``."""

from rational import Router

from . import home

router = Router()
router.include(home.router)
