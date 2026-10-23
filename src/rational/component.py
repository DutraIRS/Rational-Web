"""``Component``: a reusable, optionally stateful piece of UI rendered on the server."""

from __future__ import annotations

import asyncio
import copy
import itertools
import sys
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from .events import ClientOp
from .state import State

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

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        props: dict[str, Any] = {}
        class_vars: set[str] = set()
        for base in reversed(cls.__mro__[1:]):
            props.update(base.__dict__.get("_rw_props", {}))
            if base is not object:
                class_vars.update(n for n, a in _own_annotations(base).items() if "ClassVar" in a)
        for name, annotation in _own_annotations(cls).items():
            if name.startswith("_") or "ClassVar" in annotation or name in class_vars:
                continue
            default = cls.__dict__.get(name, _REQUIRED)
            if isinstance(default, State) or annotation.startswith("State"):
                continue
            props[name] = default
        cls._rw_props = props

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

    def touch(self, *names: str) -> None:
        """Mark state as changed after mutating it in place."""
        for name in names:
            descriptor = getattr(type(self), name, None)
            if not isinstance(descriptor, State):
                raise AttributeError(f"{type(self).__name__}.{name} is not a State attribute")
            descriptor.notify(self)

    def navigate(self, url: str) -> None:
        """After this event, send the browser to ``url`` (same-origin paths only)."""
        if not url.startswith("/") or url.startswith(("//", "/\\")):
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

    title: ClassVar[str | None] = None
    description: ClassVar[str | None] = None
    auth: ClassVar[str | None] = None

    @property
    def request(self) -> Any:
        return self.context.request
