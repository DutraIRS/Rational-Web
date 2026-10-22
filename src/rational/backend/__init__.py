from typing import Any

from .services import Service, remote

__all__ = ["Database", "Model", "Service", "remote"]


def __getattr__(name: str) -> Any:
    # SQLAlchemy is an optional dependency; import it only when asked for.
    if name in ("Database", "Model"):
        from . import database

        return getattr(database, name)
    raise AttributeError(name)
