"""Services: server-side operations, optionally exposed over HTTP with ``@remote``.

Nothing is reachable from the browser unless it is decorated with ``@remote``.
Remote methods get a typed FastAPI route (and OpenAPI entry), Pydantic
validation, authentication checks, CSRF protection for cookie sessions and
safe structured errors.
"""

from __future__ import annotations

import inspect
import logging
import re
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from fastapi import Request, Response
from pydantic import create_model

from ..concurrency import invoke
from ..errors import RationalError, Unauthorized
from ..http import csrf_ok, json_error

if TYPE_CHECKING:
    from ..app import App
    from ..context import Context
    from ..session import Session
    from .database import Database

log = logging.getLogger("rational")

F = TypeVar("F", bound=Callable[..., Any])


class Service:
    """Group related server operations. Instances are bound to one request context."""

    def __init__(self, context: Context) -> None:
        self.context = context

    @property
    def session(self) -> Session:
        return self.context.session

    @property
    def user(self) -> Any:
        return self.context.user

    @property
    def db(self) -> Database:
        return self.context.db

    def require_user(self) -> Any:
        return self.context.require_user()


@dataclass(frozen=True, slots=True)
class RemoteSpec:
    method: str
    auth: str | None
    path: str | None


def remote(
    fn: F | None = None,
    *,
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST",
    auth: Literal["required"] | None = None,
    path: str | None = None,
) -> Any:
    """Expose a service method as an HTTP endpoint.

    Use ``GET`` only for safe, idempotent reads. ``auth="required"`` rejects
    anonymous callers with 401.
    """

    def decorate(f: F) -> F:
        f.__rw_remote__ = RemoteSpec(method.upper(), auth, path)  # type: ignore[attr-defined]
        return f

    return decorate(fn) if fn is not None else decorate


def service_slug(cls: type) -> str:
    """``TodoService`` -> ``todo``; ``UserAccountService`` -> ``user-account``."""
    name = cls.__name__
    if name.endswith("Service") and name != "Service":
        name = name[: -len("Service")]
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def register_service(app: App, cls: type) -> None:
    if not (isinstance(cls, type) and issubclass(cls, Service)):
        raise TypeError("@app.service decorates Service subclasses")
    tag = service_slug(cls)
    tags = list(app.fastapi.openapi_tags or [])
    if not any(t["name"] == tag for t in tags):
        tags.append({"name": tag, "description": inspect.getdoc(cls) or ""})
        app.fastapi.openapi_tags = tags
    for name, fn in inspect.getmembers(cls, predicate=inspect.isfunction):
        spec: RemoteSpec | None = getattr(fn, "__rw_remote__", None)
        if spec is not None:
            fn.__rw_service__ = cls  # type: ignore[attr-defined]  # ClientComponent.remote(Service.method) finds its route
            _add_route(app, cls, name, fn, spec)


def _add_route(app: App, cls: type[Service], name: str, fn: Callable[..., Any], spec: RemoteSpec) -> None:
    hints = typing.get_type_hints(fn)
    params = list(inspect.signature(fn).parameters.values())[1:]
    returns = hints.get("return", Any)
    response_model = None if returns in (Any, None, type(None)) else returns

    context_params = [
        inspect.Parameter("request", inspect.Parameter.KEYWORD_ONLY, annotation=Request),
        inspect.Parameter("response", inspect.Parameter.KEYWORD_ONLY, annotation=Response),
    ]
    body_model: Any = None
    if spec.method == "GET":
        arg_params = [
            inspect.Parameter(
                p.name, inspect.Parameter.KEYWORD_ONLY, annotation=hints.get(p.name, Any), default=p.default
            )
            for p in params
        ]
    else:
        fields: dict[str, Any] = {
            p.name: (hints.get(p.name, Any), ... if p.default is p.empty else p.default) for p in params
        }
        body_model = create_model(f"{cls.__name__}_{name}_Body", **fields)
        arg_params = [inspect.Parameter("body", inspect.Parameter.KEYWORD_ONLY, annotation=body_model)]

    async def endpoint(**kwargs: Any) -> Any:
        request: Request = kwargs.pop("request")
        response: Response = kwargs.pop("response")
        ctx = await app.context_for(request)
        session = ctx.peek_session()
        if spec.method != "GET" and session is not None and not csrf_ok(request, session):
            response = json_error(403, "csrf", "Invalid CSRF token")
            await app.finish(request, response, ctx)
            return response
        if body_model is not None:
            body = kwargs.pop("body")
            kwargs = {field: getattr(body, field) for field in body_model.model_fields}
        async with app.session_lock(ctx):
            try:
                if spec.auth == "required" and ctx.user is None:
                    raise Unauthorized()
                result = await invoke(
                    getattr(cls(ctx), name),
                    kwargs=kwargs,
                    timeout=app.handler_timeout,
                    threads=app.sync_handlers == "thread",
                )
            except RationalError as e:
                error_response = json_error(e.status, e.code, e.message, details=e.details)
                await app.finish(request, error_response, ctx)
                return error_response
            except Exception:
                log.exception("error in remote %s.%s", cls.__name__, name)
                error_response = json_error(500, "internal", "Something went wrong")
                await app.finish(request, error_response, ctx)
                return error_response
            await app.finish(request, response, ctx)
            return result

    endpoint.__signature__ = inspect.Signature([*context_params, *arg_params])  # type: ignore[attr-defined]
    endpoint.__name__ = f"{cls.__name__}_{name}"
    route = spec.path or f"{app.api_prefix}/{service_slug(cls)}/{name.replace('_', '-')}"
    app.fastapi.add_api_route(
        route,
        endpoint,
        methods=[spec.method],
        response_model=response_model,
        name=f"{cls.__name__}.{name}",
        tags=[service_slug(cls)],
        summary=(fn.__doc__ or "").strip() or None,
    )
