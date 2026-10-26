"""``ClientComponent``: a component that renders and handles its events in the browser."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from fastapi.encoders import jsonable_encoder

from ..component import Component
from ..concurrency import invoke
from ..errors import RationalError, RemoteError
from ..state import State


class ClientComponent(Component):
    """A component whose code runs in the browser, compiled from Python to JavaScript.

    The server renders it first, so the page shows real content before any script loads, then the
    browser takes over ("hydrates" it): its event handlers run locally, with no request to the
    server, and every state change re-renders it on the spot. Use it for interactions that must feel
    instant (toggles, tabs, filters, live form feedback) and load data with
    ``await self.remote(Service.method, ...)``.

    ``mount()`` runs where the instance is created: on the server for the first render, in the browser
    for instances that another client component creates later. ``hydrated()`` runs in the browser once
    the instance is interactive.

    The code is a checked subset of Python; anything the compiler cannot translate is reported with
    its file and line the first time the component renders. See :doc:`/client-components`.
    """

    _rw_client: ClassVar[bool] = True
    resumable: ClassVar[bool] = False  # its state lives in the browser

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name, value in vars(cls).items():
            if isinstance(value, State) and value.scope != "component":
                raise TypeError(
                    f"{cls.__name__}.{name}: a client component's state lives in the browser, so it can only "
                    f"use State(scope='component'), not {value.scope!r}"
                )

    def hydrated(self) -> None:
        """Called in the browser once this instance is interactive. Never called on the server."""

    async def remote(self, method: Callable[..., Any], /, **args: Any) -> Any:
        """Call a ``@remote`` method of a registered service and return its result as JSON data.

        In the browser this is an HTTP request (with the session's CSRF token); on the server, during
        the first render, the method is called directly. Either way the result is plain JSON data
        (dicts, lists, strings, numbers), and any failure is raised as :class:`~rational.RemoteError`.
        """
        service = getattr(method, "__rw_service__", None)
        spec = getattr(method, "__rw_remote__", None)
        if service is None or spec is None:
            raise TypeError(
                f"{getattr(method, '__qualname__', method)!r} is not a @remote method of a registered service"
            )
        context = self.context
        app = context.app
        try:
            if spec.auth == "required" and context.user is None:
                raise RemoteError("Please sign in", code="unauthorized", status=401)
            result = await invoke(
                getattr(service(context), method.__name__),
                kwargs=args,
                timeout=app.handler_timeout if app is not None else None,
                threads=app is not None and app.sync_handlers == "thread",
            )
        except RemoteError:
            raise
        except RationalError as e:
            raise RemoteError(e.message, code=e.code, status=e.status, details=e.details) from e
        return jsonable_encoder(result)
