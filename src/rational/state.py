"""``State``: reactive attributes on components.

Reading a state attribute while a component renders records a dependency;
assigning a different value marks every dependent component for rerender.
Mutating a container in place is *not* detected: reassign it, or call
``component.touch("name")``.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, overload

from ._tracking import Cell, track_read

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
    """

    name: str
    owner: type

    def __init__(
        self, default: T = MISSING, *, factory: Callable[[], T] | None = None, scope: Scope = "component"
    ) -> None:
        if default is not MISSING and factory is not None:
            raise TypeError("pass either a default or a factory, not both")
        if default is MISSING and factory is None:
            raise TypeError("State needs a default value or a factory")
        if scope not in ("component", "page", "session"):
            raise ValueError(f"unknown state scope {scope!r}")
        self.default = default
        self.factory = factory
        self.scope = scope

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
            store[key] = self._initial()
        track_read(cell)
        return store[key]  # type: ignore[no-any-return]

    def __set__(self, instance: Component, value: T) -> None:
        store, key, cell = self._locate(instance)
        old = store.get(key, MISSING)
        store[key] = value
        if old is MISSING or not values_equal(old, value):
            self.notify(instance, cell)

    def notify(self, instance: Component, cell: Cell | None = None) -> None:
        if cell is None:
            cell = self._locate(instance)[2]
        if self.scope == "session":
            instance.context.session.bump()
        runtime = instance._rw_runtime
        if runtime is not None:
            runtime.state_changed(cell)

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


def values_equal(a: Any, b: Any) -> bool:
    """``a == b``, treating a comparison that fails or is ambiguous (arrays) as 'different'."""
    try:
        return bool(a == b)
    except Exception:
        return False
