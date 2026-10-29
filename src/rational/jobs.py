"""Background jobs and scheduled tasks.

::

    jobs = Jobs(app)                          # in memory; store=RedisJobStore(url=...) for several workers

    @jobs.job(retries=5)
    async def send_receipt(order_id: int) -> None: ...

    await send_receipt.enqueue(42)            # returns at once; a worker runs it, retrying with backoff
    await send_receipt.enqueue_in(60, 42)     # in a minute

    @jobs.every(hours=1)
    async def clean_up() -> None: ...         # once an hour, on one worker

Arguments are stored as JSON and validated against the function's annotations when the job runs.
Delivery is *at least once*: a job cut off mid-run (a crash, a deploy) runs again once its lease
expires, so write jobs that can safely run twice. The memory store loses queued jobs when the
process stops; a persistent store keeps them.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, ParamSpec, Protocol, TypeVar

import anyio.to_thread
from pydantic import validate_call
from pydantic_core import to_jsonable_python

if TYPE_CHECKING:
    from .app import App

log = logging.getLogger("rational.jobs")

P = ParamSpec("P")
R = TypeVar("R")


class JobStore(Protocol):
    """Where queued jobs wait. ``claim`` hands a due job to one worker for ``lease`` seconds."""

    async def push(self, record: bytes, due: float) -> None: ...

    async def claim(self, now: float, lease: float) -> bytes | None: ...

    async def release(self, record: bytes, retry: bytes | None = None, due: float = 0.0) -> None:
        """Finish a claimed job; with ``retry``, queue that record for ``due`` in the same step."""
        ...

    async def once(self, key: str, ttl: float) -> bool:
        """True for the first caller of ``key`` within ``ttl`` seconds, across every worker."""
        ...


class MemoryJobStore:
    """Jobs in this process's memory: for development, tests and single-worker apps."""

    def __init__(self) -> None:
        self.queued: dict[bytes, float] = {}
        self.leased: dict[bytes, float] = {}
        self._once: dict[str, float] = {}

    async def push(self, record: bytes, due: float) -> None:
        self.queued[record] = due

    async def claim(self, now: float, lease: float) -> bytes | None:
        for record, until in list(self.leased.items()):  # leases that ran out: queue again
            if until <= now:
                del self.leased[record]
                self.queued[record] = now
        due = [(at, record) for record, at in self.queued.items() if at <= now]
        if not due:
            return None
        record = min(due)[1]
        del self.queued[record]
        self.leased[record] = now + lease
        return record

    async def release(self, record: bytes, retry: bytes | None = None, due: float = 0.0) -> None:
        self.leased.pop(record, None)
        if retry is not None:
            self.queued[retry] = due

    async def once(self, key: str, ttl: float) -> bool:
        now = time.time()
        if self._once.get(key, 0.0) > now:
            return False
        self._once = {k: v for k, v in self._once.items() if v > now}
        self._once[key] = now + ttl
        return True


_CLAIM = """
for _, record in ipairs(redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', ARGV[1])) do
  redis.call('ZREM', KEYS[2], record)
  redis.call('ZADD', KEYS[1], ARGV[1], record)
end
local due = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, 1)
if #due == 0 then return false end
redis.call('ZREM', KEYS[1], due[1])
redis.call('ZADD', KEYS[2], tonumber(ARGV[1]) + tonumber(ARGV[2]), due[1])
return due[1]
"""

_RELEASE = """
redis.call('ZREM', KEYS[2], ARGV[1])
if ARGV[2] ~= '' then redis.call('ZADD', KEYS[1], ARGV[3], ARGV[2]) end
return 1
"""


class RedisJobStore:
    """Jobs in Redis (``pip install redis``): shared by every worker, kept across restarts.

    Pass a URL or a ``redis.asyncio.Redis`` client created without ``decode_responses``.
    """

    def __init__(self, client: Any = None, *, url: str | None = None, prefix: str = "rational:jobs") -> None:
        if client is None:
            if url is None:
                raise ValueError("pass a redis client or url=")
            try:
                from redis.asyncio import Redis
            except ImportError as e:
                raise ImportError("RedisJobStore needs the 'redis' package: pip install redis") from e
            client = Redis.from_url(url)
        self.client = client
        self.keys = (f"{prefix}:queued", f"{prefix}:leased")
        self.prefix = prefix

    async def push(self, record: bytes, due: float) -> None:
        await self.client.zadd(self.keys[0], {record: due})

    async def claim(self, now: float, lease: float) -> bytes | None:
        record = await self.client.eval(_CLAIM, 2, *self.keys, now, lease)
        return bytes(record) if record else None

    async def release(self, record: bytes, retry: bytes | None = None, due: float = 0.0) -> None:
        await self.client.eval(_RELEASE, 2, *self.keys, record, retry or b"", due)

    async def once(self, key: str, ttl: float) -> bool:
        return bool(await self.client.set(f"{self.prefix}:once:{key}", 1, nx=True, px=max(1, int(ttl * 1000))))


@dataclass(eq=False)
class Job(Generic[P, R]):
    """A function registered with :meth:`Jobs.job`. Calling it runs it now; ``enqueue`` runs it later."""

    fn: Callable[P, R]
    name: str
    jobs: Jobs
    retries: int = 3
    backoff: float = 2.0  # seconds before retry n: backoff ** n
    timeout: float | None = None
    _validated: Callable[..., Any] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validated = validate_call(self.fn)
        functools.update_wrapper(self, self.fn)

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        return self.fn(*args, **kwargs)

    async def enqueue(self, *args: P.args, **kwargs: P.kwargs) -> str:
        """Queue a run with these arguments and return its id."""
        return await self.jobs._push(self, 0.0, args, kwargs)

    def enqueue_in(self, seconds: float, *args: P.args, **kwargs: P.kwargs) -> Awaitable[str]:
        """Queue a run in ``seconds`` seconds and return its id."""
        return self.jobs._push(self, seconds, args, kwargs)

    async def _run(self, args: list[Any], kwargs: dict[str, Any]) -> None:
        if inspect.iscoroutinefunction(self.fn):
            async with asyncio.timeout(self.timeout):
                await self._validated(*args, **kwargs)
        else:  # a plain function may block: run it in a thread (it cannot be interrupted)
            await anyio.to_thread.run_sync(functools.partial(self._validated, *args, **kwargs))


class Jobs:
    """Runs jobs on ``concurrency`` workers in each process, while the app runs.

    ``Jobs(app)`` starts and stops with the app. Without an app, call :meth:`start` and :meth:`stop`.
    """

    def __init__(
        self,
        app: App | None = None,
        *,
        store: JobStore | None = None,
        concurrency: int = 4,
        poll: float = 1.0,
        lease: float = 300.0,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        self.store: JobStore = MemoryJobStore() if store is None else store
        self.concurrency = concurrency
        self.poll = poll
        self.lease = lease
        self.registry: dict[str, Job[Any, Any]] = {}
        self._schedules: list[tuple[Job[Any, Any], float]] = []
        self._workers: list[asyncio.Task[None]] = []
        self._wake: asyncio.Event | None = None  # made in start(), on the loop that runs the workers
        self._stopping = False
        if app is not None:
            app.on_startup(self.start)
            app.on_shutdown(self.stop)

    def job(
        self, *, name: str | None = None, retries: int = 3, backoff: float = 2.0, timeout: float | None = None
    ) -> Callable[[Callable[P, R]], Job[P, R]]:
        """Register a function (``async def`` or plain) as a job. ``name`` defaults to its qualified name."""

        def decorator(fn: Callable[P, R]) -> Job[P, R]:
            key = name or f"{fn.__module__}.{fn.__qualname__}"
            if key in self.registry:
                raise ValueError(f"a job named {key!r} is already registered")
            job: Job[P, R] = Job(fn, key, self, retries, backoff, timeout)
            self.registry[key] = job
            return job

        return decorator

    def every(
        self, *, seconds: float = 0, minutes: float = 0, hours: float = 0, days: float = 0, retries: int = 3
    ) -> Callable[[Callable[[], R]], Job[[], R]]:
        """Run a function with no arguments once per interval, on one worker of all the app's processes.

        Intervals are counted from the Unix epoch, so ``hours=24`` runs at midnight UTC.
        """
        interval = seconds + 60 * minutes + 3600 * hours + 86400 * days
        if interval <= 0:
            raise ValueError("every() needs a positive interval")

        def decorator(fn: Callable[[], R]) -> Job[[], R]:
            job = self.job(retries=retries)(fn)
            self._schedules.append((job, interval))
            return job

        return decorator

    async def _push(self, job: Job[Any, Any], delay: float, args: Any, kwargs: Any) -> str:
        inspect.signature(job.fn).bind(*args, **kwargs)  # wrong arguments fail here, not later on a worker
        job_id = secrets.token_hex(8)
        record = {"id": job_id, "job": job.name, "args": list(args), "kwargs": kwargs, "attempt": 0}
        await self.store.push(_dump(record), time.time() + max(0.0, delay))
        if self._wake is not None:
            self._wake.set()
        return job_id

    async def start(self) -> None:
        """Start the workers and schedules of this process."""
        if self._workers:
            return
        self._stopping = False
        self._wake = asyncio.Event()
        self._workers = [asyncio.create_task(self._work()) for _ in range(self.concurrency)]
        self._workers += [asyncio.create_task(self._tick(job, every)) for job, every in self._schedules]

    async def stop(self, grace: float = 10.0) -> None:
        """Stop taking jobs, let running ones finish for up to ``grace`` seconds, then cancel them."""
        self._stopping = True
        if self._wake is not None:
            self._wake.set()
        workers, self._workers = self._workers, []
        if workers:
            _, pending = await asyncio.wait(workers, timeout=grace)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def run_pending(self) -> int:
        """Run every job that is due now, in this task, and return how many ran (for tests and scripts)."""
        count = 0
        while (record := await self.store.claim(time.time(), self.lease)) is not None:
            await self._handle(record)
            count += 1
        return count

    async def _work(self) -> None:
        while not self._stopping:
            record = await self.store.claim(time.time(), self.lease)
            if record is None:
                assert self._wake is not None
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self.poll)
                continue
            await self._handle(record)

    async def _tick(self, job: Job[Any, Any], every: float) -> None:
        while not self._stopping:
            slot = int(time.time() // every)
            if await self.store.once(f"{job.name}:{slot}", every):
                await job.enqueue()
            await asyncio.sleep((slot + 1) * every - time.time())

    async def _handle(self, record: bytes) -> None:
        data = json.loads(record)
        job = self.registry.get(data["job"])
        if job is None:
            log.error("job %s (%s) is not registered in this process; dropped", data["job"], data["id"])
            await self.store.release(record)
            return
        try:
            await job._run(data["args"], data["kwargs"])
        except asyncio.CancelledError:
            raise  # stopping: the lease runs out and another worker takes the job
        except Exception:
            attempt = data["attempt"] + 1
            if attempt > job.retries:
                log.exception("job %s (%s) failed after %d attempts", job.name, data["id"], attempt)
                await self.store.release(record)
                return
            log.warning("job %s (%s) failed, retry %d of %d", job.name, data["id"], attempt, job.retries, exc_info=True)
            retry = _dump({**data, "attempt": attempt})
            await self.store.release(record, retry, time.time() + job.backoff**attempt)
            return
        await self.store.release(record)


def _dump(record: dict[str, Any]) -> bytes:
    try:
        return json.dumps(to_jsonable_python(record), separators=(",", ":")).encode()
    except Exception as e:
        raise TypeError(f"job arguments must be JSON-compatible (str, numbers, lists, dicts, models): {e}") from None
