"""Background jobs: queueing, validation, retries, leases, schedules, and both stores."""

import asyncio
import time

import fakeredis
import pytest
from pydantic import BaseModel

from rational import App
from rational.jobs import Jobs, MemoryJobStore, RedisJobStore


@pytest.fixture(params=["memory", "redis"])
def store(request):
    return MemoryJobStore() if request.param == "memory" else RedisJobStore(fakeredis.FakeAsyncRedis())


class Order(BaseModel):
    id: int
    total: float


async def test_jobs_run_with_validated_arguments(store):
    jobs = Jobs(store=store)
    seen = []

    @jobs.job()
    async def receipt(order: Order, copies: int = 1) -> None:
        seen.append((order, copies))

    @jobs.job()
    def blocking(text: str) -> None:  # plain functions run in a worker thread
        seen.append(text)

    await receipt.enqueue(Order(id=1, total=9.5), copies=2)
    await blocking.enqueue("hi")
    assert await jobs.run_pending() == 2
    assert seen == [(Order(id=1, total=9.5), 2), "hi"]  # the model came back from JSON as a model
    await receipt(Order(id=2, total=1), copies=3)  # calling the job runs it now
    assert seen[-1][1] == 3


async def test_bad_arguments_fail_when_queued():
    jobs = Jobs()

    @jobs.job()
    async def greet(name: str) -> None: ...

    with pytest.raises(TypeError):
        await greet.enqueue()  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="JSON-compatible"):
        await greet.enqueue(object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="already registered"):
        jobs.job(name=greet.name)(lambda: None)


async def test_failures_are_retried_then_dropped(store, caplog):
    jobs = Jobs(store=store)
    calls = []

    @jobs.job(retries=2, backoff=0)  # backoff 0: retries are due at once
    async def flaky() -> None:
        calls.append(1)
        raise RuntimeError("boom")

    @jobs.job(timeout=0.01, retries=0)
    async def slow() -> None:
        await asyncio.sleep(1)

    await flaky.enqueue()
    await slow.enqueue()
    await jobs.run_pending()
    assert len(calls) == 3  # the first run and two retries
    assert "failed after 3 attempts" in caplog.text and "failed after 1 attempts" in caplog.text
    assert await jobs.run_pending() == 0


async def test_a_job_cut_off_runs_again_after_its_lease(store):
    await store.push(b'{"id":"1"}', 0)
    assert await store.claim(now=10, lease=30) == b'{"id":"1"}'
    assert await store.claim(now=20, lease=30) is None  # still leased
    assert await store.claim(now=41, lease=30) == b'{"id":"1"}'  # lease ran out: handed out again
    await store.release(b'{"id":"1"}')
    assert await store.claim(now=100, lease=30) is None


async def test_once_is_first_come_across_workers(store):
    assert await store.once("tick:1", 60)
    assert not await store.once("tick:1", 60)
    assert await store.once("tick:2", 60)


async def test_unknown_jobs_are_dropped(caplog):
    store = MemoryJobStore()
    await store.push(b'{"id":"x","job":"gone","args":[],"kwargs":{},"attempt":0}', 0)
    assert await Jobs(store=store).run_pending() == 1
    assert "not registered" in caplog.text and not store.queued and not store.leased


async def test_workers_run_jobs_while_the_app_runs():
    app = App()
    jobs = Jobs(app, concurrency=2, poll=5)
    done = asyncio.Event()

    @jobs.job()
    async def ping() -> None:
        done.set()

    async with app.fastapi.router.lifespan_context(app.fastapi):
        await ping.enqueue()
        await asyncio.wait_for(done.wait(), 2)  # woken at once, not after the 5 s poll
    assert not jobs._workers


async def test_schedules_run_once_per_interval_across_workers():
    store = MemoryJobStore()
    runs = []
    workers = [Jobs(store=store, poll=0.01) for _ in range(2)]
    for jobs in workers:

        @jobs.every(seconds=0.2)
        async def tick() -> None:
            runs.append(time.time())

    started = time.time()
    for jobs in workers:
        await jobs.start()
    await asyncio.sleep(0.5)
    for jobs in workers:
        await jobs.stop()
    slots = int(time.time() // 0.2) - int(started // 0.2) + 1  # intervals the test touched
    assert 1 <= len(runs) <= slots  # at most one run per interval, not one per worker

    with pytest.raises(ValueError, match="positive interval"):
        Jobs().every()


def test_jobs_settings_are_checked():
    with pytest.raises(ValueError, match="concurrency"):
        Jobs(concurrency=0)
    with pytest.raises(ValueError, match="redis client or url"):
        RedisJobStore()
