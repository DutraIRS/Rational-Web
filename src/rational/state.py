"""``State``: reactive attributes on components, and what is built on them.

Reading a state attribute while a component renders records a dependency;
assigning a different value marks every dependent component for rerender.
Mutating a container in place is *not* detected: reassign it, or call
``component.touch("name")``.

``computed`` derives a cached value from state, ``watch`` runs a method when state changes, and
``Binding`` (``component.bind("name")``) ties a form control to a state attribute.
"""

from __future__ import annotations

import copy
import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, overload

from pydantic import TypeAdapter, ValidationError

from ._tracking import Cell, changed, reads, track_read, version

if TYPE_CHECKING:
    from .component import Component

T = TypeVar("T")
Scope = Literal["component", "page", "session"]


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING: Any = _Missing()


class State(Generic[T]):
    """Declare reactive state.

    ``scope="component"`` (default): one value per mounted component instance.
    ``scope="page"``: one value per page view, shared by all instances of the class.
    ``scope="session"``: one value per browser session, shared across tabs. Other tabs
    pick up changes on their next event.

    ``query="q"`` keeps the value in the page's URL (``?q=...``): it starts from the query string
    (converted to the default's type) and changes replace it, so a search can be shared, bookmarked
    and reloaded. The default value leaves the parameter out.
    """

    name: str
    owner: type

    def __init__(
        self,
        default: T = MISSING,
        *,
        factory: Callable[[], T] | None = None,
        scope: Scope = "component",
        query: str | None = None,
    ) -> None:
        if default is not MISSING and factory is not None:
            raise TypeError("pass either a default or a factory, not both")
        if default is MISSING and factory is None:
            raise TypeError("State needs a default value or a factory")
        if scope not in ("component", "page", "session"):
            raise ValueError(f"unknown state scope {scope!r}")
        if query is not None and (scope == "session" or not isinstance(default, (str, int, float, bool))):
            raise TypeError("query= keeps a str, int, float or bool default of one page in the URL")
        self.default = default
        self.factory = factory
        self.scope = scope
        self.query = query

    def __set_name__(self, owner: type, name: str) -> None:
        self.owner = owner
        self.name = name

    @overload
    def __get__(self, instance: None, owner: type) -> State[T]: ...
    @overload
    def __get__(self, instance: Component, owner: type) -> T: ...

    def __get__(self, instance: Component | None, owner: type) -> State[T] | T:
        if instance is None:
            return self
        store, key, cell = self._locate(instance)
        if key not in store:
            store[key] = self._from_query(instance) if self.query else self._initial()
        track_read(cell)
        return store[key]  # type: ignore[no-any-return]

    def __set__(self, instance: Component, value: T) -> None:
        store, key, cell = self._locate(instance)
        old = store.get(key, MISSING)
        store[key] = value
        if old is MISSING or not values_equal(old, value):
            self.notify(instance, cell, old)
            if self.query and instance._rw_runtime is not None:
                text = None if values_equal(value, self.default) else _query_text(value)
                instance._rw_runtime.add_action({"op": "query", "name": self.query, "value": text})

    def notify(self, instance: Component, cell: Cell | None = None, old: Any = MISSING) -> None:
        if cell is None:
            cell = self._locate(instance)[2]
        changed()
        if self.scope == "session":
            instance.context.session.bump()
        runtime = instance._rw_runtime
        if runtime is not None:
            runtime.state_changed(cell, old)

    def _from_query(self, instance: Component) -> T:
        """The value in the page's query string, if the page request has one that fits."""
        runtime = instance._rw_runtime
        request = runtime.context.request if runtime is not None else None
        if request is None or request.method != "GET" or self.query is None:  # only a page load has the URL
            return self._initial()
        raw = request.query_params.get(self.query)
        if raw is None:
            return self._initial()
        try:
            value: T = TypeAdapter(type(self.default)).validate_python(raw)
        except ValidationError:
            return self._initial()  # a hand-edited or outdated link: start from the default
        return value

    def _initial(self) -> T:
        if self.factory is not None:
            return self.factory()
        return copy.deepcopy(self.default)

    def _locate(self, instance: Component) -> tuple[dict[str, Any], str, Cell]:
        if self.scope == "component":
            return instance._rw_state, self.name, ("c", instance._rw_uid, self.name)
        key = f"{self.owner.__module__}.{self.owner.__qualname__}.{self.name}"
        if self.scope == "page":
            runtime = instance._rw_runtime
            if runtime is None:
                raise RuntimeError(f"page-scoped state {key} is only available once mounted")
            return runtime.page_state, key, ("p", key)
        session = instance.context.session
        return session.state, key, ("s", key)


class StateMismatch(Exception):  # noqa: N818 - a condition, not a failure of this code
    """Saved state no longer fits the component: it was renamed, removed or retyped since it was saved."""


def class_name(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def restorable(component: Any, kind: str, saved: dict[str, Any]) -> dict[str, Any]:
    """``saved`` if it still fits ``component`` (saved as a ``kind``); else raise ``StateMismatch``.

    A deploy may rename a component's ``State``, remove it or change what it holds. Restoring an old
    value into new code would show a wrong page instead of failing, so anything that no longer
    fits fails, and the browser loads the page afresh.
    """
    cls = type(component)
    if kind != class_name(cls):
        raise StateMismatch(f"{kind} was saved where {class_name(cls)} now is")
    states = {
        name: attr
        for klass in reversed(cls.__mro__)
        for name, attr in vars(klass).items()
        if isinstance(attr, State) and attr.scope == "component"
    }
    for name, value in saved.items():
        state = states.get(name)
        if state is None:
            raise StateMismatch(f"{cls.__name__}.{name} is no longer a State")
        expected = state._initial()
        if expected is not None and value is not None and not _same_kind(expected, value):
            raise StateMismatch(
                f"{cls.__name__}.{name} now holds {type(expected).__name__}, not {type(value).__name__}"
            )
    return saved


def _same_kind(expected: Any, value: Any) -> bool:
    if isinstance(expected, bool) or isinstance(value, bool):
        return type(expected) is type(value)
    if isinstance(expected, (int, float)):
        return isinstance(value, (int, float))
    if isinstance(expected, (list, tuple)):
        return isinstance(value, (list, tuple))  # JSON turns tuples into lists
    return isinstance(value, type(expected))


def _query_text(value: Any) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


def values_equal(a: Any, b: Any) -> bool:
    """``a == b``, treating a comparison that fails or is ambiguous (arrays) as 'different'."""
    try:
        return bool(a == b)
    except Exception:
        return False


class computed(Generic[T]):  # noqa: N801 - used as a decorator, like property
    """A value derived from state, read like an attribute and cached until state changes::

        @computed
        def total(self) -> int:
            return sum(item.price for item in self.items)

    The cache is shared by every read until any state, session data or props change. Components that
    read it re-render when the state it used changes, exactly as if they had read that state.
    """

    def __init__(self, fn: Callable[[Any], T]) -> None:
        self.fn = fn
        self.name = fn.__name__
        self.__doc__ = fn.__doc__

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    @overload
    def __get__(self, instance: None, owner: type) -> computed[T]: ...
    @overload
    def __get__(self, instance: object, owner: type) -> T: ...

    def __get__(self, instance: object | None, owner: type) -> computed[T] | T:
        if instance is None:
            return self
        cache: dict[str, tuple[int, Any, set[Cell]]] = instance.__dict__.setdefault("_rw_computed", {})
        hit = cache.get(self.name)
        if hit is not None and hit[0] == version.value:
            for cell in hit[2]:  # the reader depends on what the value was computed from
                track_read(cell)
            return hit[1]  # type: ignore[no-any-return]
        cells: set[Cell] = set()
        token = reads.set(cells)
        try:
            value = self.fn(instance)
        finally:
            reads.reset(token)
        for cell in cells:  # nested computed values collected into ``cells``; the outer reader still tracks
            track_read(cell)
        cache[self.name] = (version.value, value, cells)
        return value


def watch(*names: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Call the decorated method after any of the named ``State`` attributes changes::

        @watch("query")
        async def search(self, new: str, old: str) -> None:
            self.results = await self.use(Search).find(new)

    The method takes ``(new, old)``, ``(new)`` or nothing, may be async, and runs before the page
    re-renders. Values set while the component mounts do not trigger it.
    """
    if not names or not all(isinstance(n, str) for n in names):
        raise TypeError("@watch takes the names of State attributes: @watch('count')")

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn._rw_watch = names  # type: ignore[attr-defined]
        return fn

    return decorate


def call_watcher(method: Callable[..., Any], new: Any, old: Any) -> Any:
    """Call a bound watcher with as many of ``(new, old)`` as it takes."""
    positional = [
        p
        for p in inspect.signature(method).parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    return method(*(new, old)[: len(positional)])


class Binding:
    """A form control tied to a ``State`` attribute, both ways: ``Input("Name", bind=self.bind("name"))``.

    The control shows the attribute's value, and what the user types is converted to the type of the
    current value (``int``, ``float``, ``bool`` or ``str``) and stored. Input that is not a valid value
    yet (``"-"`` in a number field) is ignored, so the last valid value stays.
    """

    __slots__ = ("component", "name")

    def __init__(self, component: Component, name: str) -> None:
        if not isinstance(getattr(type(component), name, None), State):
            raise AttributeError(f"{type(component).__name__}.{name} is not a State attribute; bind() needs one")
        self.component = component
        self.name = name

    @property
    def value(self) -> Any:
        return getattr(self.component, self.name)

    def set(self, value: Any) -> None:
        try:
            setattr(self.component, self.name, convert_like(value, self.value))
        except (TypeError, ValueError):
            return None


def convert_like(value: Any, current: Any) -> Any:
    """``value`` (from a form control) converted to the type of ``current``."""
    if isinstance(current, bool):
        return value if isinstance(value, bool) else str(value).strip().lower() in ("true", "on", "1", "yes")
    if isinstance(current, int):
        return int(str(value).strip())
    if isinstance(current, float):
        return float(str(value).strip())
    if isinstance(current, str):
        return "" if value is None else str(value)
    return value
