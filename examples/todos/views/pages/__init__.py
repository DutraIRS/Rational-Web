"""Every page of the app, combined into one router for ``app.py``."""

from rational import Router

from . import login, todos

router = Router()
router.include(todos.router)
router.include(login.router)
