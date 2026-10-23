"""Running event handlers and remote methods: timeouts and thread offload.

``async def`` handlers always run on the event loop. A plain ``def`` handler runs on the loop
too unless thread offload is on, in which case it runs in a worker thread so blocking I/O does
not stall every other request. Either way the session and page locks stay held for the whole
call, so state is still changed by one handler at a time.

Set the defaults on the app (``App(handler_timeout=..., sync_handlers="thread")``) and override
them per handler with :func:`timeout` and :func:`threaded`.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable
from typing import Any, Literal, TypeVar, overload

import anyio.to_thread

from .errors import RationalError

F = TypeVar("F", bound=Callable[..., Any])

SyncHandlers = Literal["loop", "thread"]

_TIMEOUT_ATTR = "__rational_timeout__"
_THREAD_ATTR = "__rational_threaded__"


class HandlerTimeout(RationalError):  # noqa: N818 - public name mirrors NotFound, Forbidden
    """A handler or remote method ran longer than its time limit."""

    status = 504
    code = "timeout"

    def default_message(self) -> str:
        return "The request took too long"


def timeout(seconds: float | None) -> Callable[[F], F]:
    """Limit one handler or ``@remote`` method; ``timeout(None)`` removes the app-wide limit.

    A timed-out ``async def`` handler is cancelled. A handler running in a worker thread cannot
    be interrupted: the request is answered with a timeout error, but the thread runs to the end.
    """
    if seconds is not None and seconds <= 0:
        raise ValueError("timeout must be a positive number of seconds or None")

    def decorator(fn: F) -> F:
        setattr(fn, _TIMEOUT_ATTR, seconds)
        return fn

    return decorator


@overload
def threaded(fn: F) -> F: ...
@overload
def threaded(*, enabled: bool = True) -> Callable[[F], F]: ...
def threaded(fn: F | None = None, *, enabled: bool = True) -> F | Callable[[F], F]:
    """Run a plain ``def`` handler in a worker thread (or, with ``enabled=False``, on the loop).

    ``@threaded`` and ``@threaded(enabled=False)`` override ``App(sync_handlers=...)``.
    ``async def`` handlers are unaffected.
    """

    def decorator(target: F) -> F:
        setattr(target, _THREAD_ATTR, enabled)
        return target

    return decorator(fn) if fn is not None else decorator


async def invoke(
    fn: Callable[..., Any],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    *,
    timeout: float | None = None,
    threads: bool = False,
) -> Any:
    """Call ``fn(*args, **kwargs)`` and await its result, applying the effective limits.

    ``timeout`` and ``threads`` are the app defaults; the decorators above take precedence.
    """
    limit = getattr(fn, _TIMEOUT_ATTR, timeout)
    offload = getattr(fn, _THREAD_ATTR, threads)
    call = functools.partial(fn, *args, **(kwargs or {}))

    async def run() -> Any:
        if offload and not inspect.iscoroutinefunction(fn):
            result = await anyio.to_thread.run_sync(call)
        else:
            result = call()
        if inspect.isawaitable(result):
            result = await result
        return result

    if limit is None:
        return await run()
    deadline = asyncio.timeout(limit)
    try:
        async with deadline:
            return await run()
    except TimeoutError:
        if deadline.expired():
            raise HandlerTimeout() from None
        raise
