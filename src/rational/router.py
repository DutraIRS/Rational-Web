"""``Router``: declare pages, sockets and services in their own modules, compose them in one place.

Like FastAPI's ``APIRouter`` or Flask's blueprints, a router only *records* what it is
given; ``App.include(router)`` registers everything. Modules never need to import the app
instance, so multi-file projects have no circular imports::

    # myapp/pages/admin.py
    router = Router(prefix="/admin")

    @router.page("/")              # served at /admin
    class AdminHome(Page): ...

    # app.py (the composition root)
    app = App()
    app.include(admin.router)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from .component import Page

if TYPE_CHECKING:
    from .pages import PathValues

P = TypeVar("P", bound=type[Page])
T = TypeVar("T", bound=type)


@dataclass(frozen=True, slots=True)
class PageEntry:
    path: str
    page: type[Page]
    title: str | None = None
    auth: str | None = None
    paths: PathValues | Callable[[], PathValues] | None = None


@dataclass
class Router:
    prefix: str = ""
    pages: list[PageEntry] = field(default_factory=list)
    services: list[type] = field(default_factory=list)
    sockets: list[tuple[str, type]] = field(default_factory=list)
    startup: list[Callable[[], Any]] = field(default_factory=list)
    shutdown: list[Callable[[], Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.prefix = "/" + self.prefix.strip("/") if self.prefix.strip("/") else ""

    def page(
        self,
        path: str,
        *,
        title: str | None = None,
        auth: str | None = None,
        paths: PathValues | Callable[[], PathValues] | None = None,
    ) -> Callable[[P], P]:
        """Record a ``Page`` subclass at ``path`` (relative to the router's prefix); see ``App.page``."""

        def decorator(cls: P) -> P:
            self.pages.append(PageEntry(join(self.prefix, path), cls, title, auth, paths))
            return cls

        return decorator

    def socket(self, path: str) -> Callable[[T], T]:
        """Record a ``Socket`` class at ``path`` (relative to the router's prefix); see ``App.socket``."""

        def decorator(cls: T) -> T:
            self.sockets.append((join(self.prefix, path), cls))
            return cls

        return decorator

    def service(self, cls: T) -> T:
        """Record a ``Service`` to expose its ``@remote`` methods."""
        self.services.append(cls)
        return cls

    def on_startup(self, fn: Callable[[], Any]) -> Callable[[], Any]:
        self.startup.append(fn)
        return fn

    def on_shutdown(self, fn: Callable[[], Any]) -> Callable[[], Any]:
        self.shutdown.append(fn)
        return fn

    def include(self, other: Router) -> None:
        """Merge another router's records into this one, under this router's prefix."""
        self.pages.extend(PageEntry(join(self.prefix, e.path), e.page, e.title, e.auth, e.paths) for e in other.pages)
        self.sockets.extend((join(self.prefix, path), cls) for path, cls in other.sockets)
        self.services.extend(other.services)
        self.startup.extend(other.startup)
        self.shutdown.extend(other.shutdown)


def join(prefix: str, path: str) -> str:
    """``join("/admin", "/")`` -> ``/admin``; ``join("/admin", "/users")`` -> ``/admin/users``."""
    if not prefix:
        return path
    return prefix if path in ("", "/") else prefix + "/" + path.lstrip("/")
