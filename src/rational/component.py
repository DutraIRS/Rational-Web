"""``Component``: a reusable, optionally stateful piece of UI rendered on the server."""

from __future__ import annotations

import asyncio
import copy
import itertools
import sys
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeVar

from ._tracking import changed
from .events import ClientOp
from .http import is_local_path
from .state import Binding, State, values_equal

if TYPE_CHECKING:
    from .app import App
    from .backend.services import Service
    from .context import Context
    from .runtime import PageRuntime
    from .styling.style import Style

S = TypeVar("S", bound="Service")

_REQUIRED: Any = type("REQUIRED", (), {"__repr__": lambda self: "REQUIRED"})()
_uids = itertools.count(1)


def _own_annotations(cls: type) -> dict[str, str]:
    """Annotation *strings* declared directly on ``cls`` (works with lazy annotations)."""
    if sys.version_info >= (3, 14):
        import annotationlib

        raw = annotationlib.get_annotations(cls, format=annotationlib.Format.STRING)
    else:
        raw = cls.__dict__.get("__annotations__", {})
    return {k: v if isinstance(v, str) else getattr(v, "__name__", repr(v)) for k, v in raw.items()}


class Component:
    """Subclass and implement ``render()``.

    Class-level annotations declare *props* (constructor keywords)::

        class Greeting(Component):
            name: str
            excited: bool = False

            def render(self):
                return Text(f"Hello, {self.name}{'!' if self.excited else '.'}")

    ``State`` attributes declare reactive state. Positional arguments become
    ``self.children``. ``key=`` gives a stable identity among siblings and
    ``style=`` is merged into the component's root element.
    """

    _rw_props: ClassVar[dict[str, Any]] = {}
    _rw_watchers: ClassVar[dict[str, list[str]]] = {}
    _rw_client: ClassVar[bool] = False  # True for ClientComponent: rendered and run in the browser
    resumable: ClassVar[bool] = True  # False: this component's state is not saved in page snapshots
    _rw_reserved: ClassVar[frozenset[str]] = frozenset()  # annotated attributes that are never props

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        props: dict[str, Any] = {}
        class_vars: set[str] = set()
        for base in reversed(cls.__mro__[1:]):
            props.update(base.__dict__.get("_rw_props", {}))
            if base is not object:
                class_vars.update(n for n, a in _own_annotations(base).items() if "ClassVar" in a)
        for name, annotation in _own_annotations(cls).items():
            if name.startswith("_") or "ClassVar" in annotation or name in class_vars or name in cls._rw_reserved:
                continue
            default = cls.__dict__.get(name, _REQUIRED)
            if isinstance(default, State) or annotation.startswith("State"):
                continue
            props[name] = default
        cls._rw_props = props
        watchers: dict[str, list[str]] = {k: list(v) for k, v in cls._rw_watchers.items()}
        for attr, value in vars(cls).items():
            for state_name in getattr(value, "_rw_watch", ()):
                if not isinstance(getattr(cls, state_name, None), State):
                    raise TypeError(f"{cls.__name__}.{attr}: @watch({state_name!r}) needs a State attribute")
                watchers.setdefault(state_name, []).append(attr)
        cls._rw_watchers = watchers

    def __init__(self, *children: Any, key: str | int | None = None, style: Style | None = None, **props: Any) -> None:
        self._rw_uid = next(_uids)
        self._rw_state: dict[str, Any] = {}
        self._rw_runtime: PageRuntime | None = None
        self.cid: str | None = None
        self.path: str | None = None
        self.children = children
        self.key = None if key is None else str(key)
        self.style = style
        for name, default in self._rw_props.items():
            if name in props:
                setattr(self, name, props.pop(name))
            elif default is _REQUIRED:
                raise TypeError(f"{type(self).__name__}() missing required prop {name!r}")
            else:
                setattr(self, name, copy.copy(default) if isinstance(default, (list, dict, set)) else default)
        if props:
            raise TypeError(f"{type(self).__name__}() got unexpected props: {', '.join(sorted(props))}")

    # -- lifecycle hooks -------------------------------------------------------------

    def render(self) -> Any:
        raise NotImplementedError(f"{type(self).__name__}.render() is not implemented")

    def mount(self) -> None | Awaitable[None]:
        """Called once, before the first render of this instance. May be async."""
        return None

    def unmount(self) -> None:
        """Called when the instance leaves the tree."""

    # -- server-side helpers ------------------------------------------------------------

    @property
    def context(self) -> Context:
        return self._require_runtime().context

    @property
    def app(self) -> App | None:
        return self.context.app

    def t(self, key: str, **params: Any) -> str:
        """Translate ``key`` for the visitor's locale (see :mod:`rational.i18n`)."""
        return self.context.t(key, **params)

    def use(self, service: type[S]) -> S:
        """An instance of ``service`` bound to the current request context."""
        return service(self.context)

    def bind(self, name: str) -> Binding:
        """Tie a form control to State ``name`` both ways: ``Input("Name", bind=self.bind("name"))``."""
        return Binding(self, name)

    def provide(self, key: str, value: Any) -> None:
        """Make ``value`` available to every component rendered inside this one (``self.inject(key)``).

        Call it in ``mount()`` or at the start of ``render()``. To share changing data, provide a
        component (or any object with State) rather than a plain value.
        """
        self.__dict__.setdefault("_rw_provided", {})[key] = value

    def inject(self, key: str, default: Any = _REQUIRED) -> Any:
        """The value the nearest enclosing component provided under ``key``."""
        runtime = self._require_runtime()
        cid = runtime.parent.get(str(self.cid))
        while cid is not None:
            provided = runtime.components[cid].__dict__.get("_rw_provided")
            if provided is not None and key in provided:
                return provided[key]
            cid = runtime.parent.get(cid)
        if default is _REQUIRED:
            raise LookupError(f"no component above {type(self).__name__} provides {key!r}")
        return default

    def touch(self, *names: str) -> None:
        """Mark state as changed after mutating it in place."""
        for name in names:
            descriptor = getattr(type(self), name, None)
            if not isinstance(descriptor, State):
                raise AttributeError(f"{type(self).__name__}.{name} is not a State attribute")
            descriptor.notify(self)

    def navigate(self, url: str) -> None:
        """After this event, send the browser to ``url`` (same-origin paths only)."""
        if not is_local_path(url):
            raise ValueError(f"navigate() takes a same-origin path like '/todos', not {url!r}")
        self._require_runtime().add_action({"op": "navigate", "url": url})

    def run_js(self, *ops: ClientOp) -> None:
        """After this event's patches are applied, run declarative ``js.*`` operations."""
        self._require_runtime().add_action({"op": "js", "ops": [op.to_json() for op in ops]})

    def run_task(self, fn: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kwargs: Any) -> asyncio.Task[None]:
        """Run ``async def fn(*args, **kwargs)`` in the background for as long as this component is mounted.

        State the task changes is pushed to the browser over a server-sent-events stream. The task is
        cancelled when the component unmounts or the page expires. Exceptions are logged, not raised.
        """
        return self._require_runtime().spawn(self, fn, args, kwargs)

    def _require_runtime(self) -> PageRuntime:
        if self._rw_runtime is None:
            raise RuntimeError(f"{type(self).__name__} is not mounted")
        return self._rw_runtime

    def _rw_adopt(self, fresh: Component) -> None:
        """Take props from a freshly constructed twin, keeping state and identity."""
        for name in self._rw_props:
            if name in fresh.__dict__:
                if not values_equal(getattr(self, name, None), fresh.__dict__[name]):
                    changed()  # computed values may depend on props
                setattr(self, name, fresh.__dict__[name])
        self.children = fresh.children
        self.style = fresh.style

    def __repr__(self) -> str:
        ident = f" {self.cid}" if self.cid else ""
        return f"<{type(self).__name__}{ident}>"


class Page(Component):
    """A routable component. Path parameters are declared as annotated props.

    One instance exists per page view; it is the root of that view's component tree.
    """

    auth: ClassVar[str | None] = None
    _rw_reserved = frozenset(
        {"title", "description", "lang", "dir", "favicon", "head_start", "head_end"}
        | {"image", "canonical", "noindex", "alternates", "structured_data"}
    )

    # The HTML document around the page: set these on the class, or in ``mount()`` from the
    # page's data (one class serving many pages, like ``/{lang}/docs/{slug}.html``).
    title: str | None = None
    description: str | None = None
    lang: str | None = None  # <html lang>; default: the request's locale
    dir: Literal["ltr", "rtl", "auto"] | None = None  # <html dir>: "rtl" for Arabic, Hebrew, Persian, Urdu
    favicon: str | Literal[False] | None = None  # None: App(favicon=...); False: no icon link at all
    head_start: str = ""  # trusted markup right after <meta charset>: a CSP <meta>, early metas
    head_end: str = ""  # trusted markup closing <head>, after Rational's and the app's stylesheets
    # Search engines and link previews, written when the app has rational.seo.Seo:
    image: str | None = None  # the preview image (Open Graph); default: Seo(image=...)
    canonical: str | None = None  # the page's one true URL, if others show the same content
    noindex: bool = False  # ask search engines to leave this page out (and keep it out of the sitemap)
    alternates: dict[str, str] | None = None  # translations: {"es": "/es/docs/faq.html", ...}
    structured_data: Any = None  # schema.org data, written as JSON-LD (see rational.seo.structured)

    @property
    def request(self) -> Any:
        return self.context.request
