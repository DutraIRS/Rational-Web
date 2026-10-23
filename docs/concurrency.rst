Concurrency
===========

How events are processed
------------------------

Each browser event is one HTTP request. The server handles it in this order:

1. Validate the request and apply the per-session rate limit.
2. Take the session lock and the page lock. Events for one session run one at a time.
3. Reject the event with ``409 stale_revision`` if the page revision (``rev``) is out of date.
4. Run the handler, re-render the components that changed, and answer with patches.

The browser also sends one event at a time per page and coalesces rapid input events.
Different sessions never wait for each other.

Because the locks are held while a handler runs, a slow handler delays other tabs of the
same session. Keep handlers short, or move slow work to a service.

Time limits
-----------

Give handlers a deadline so one stuck call cannot hold a session forever::

    app = App(handler_timeout=10)

    class Report(Component):
        @timeout(60)           # this handler may take longer
        async def export(self): ...

        @timeout(None)         # and this one has no limit
        async def stream(self): ...

An overrun answers ``504`` with the error code ``timeout`` (:class:`rational.HandlerTimeout`).
The same limits apply to ``@remote`` service methods. A ``TimeoutError`` raised by your own
code is not mistaken for a handler timeout.

Synchronous handlers
--------------------

By default a plain ``def`` handler runs on the event loop, so blocking calls stall every
request in the process. Two ways to avoid that:

* ``App(sync_handlers="thread")`` runs every synchronous handler in a worker thread.
* ``@threaded`` does so for one handler; ``@threaded(enabled=False)`` keeps one on the loop.

Rendering and ``mount`` always stay on the loop. ``async def`` handlers are never offloaded.

.. warning::

   A thread cannot be cancelled. If a threaded handler times out the client gets a ``504``,
   but the thread keeps running and may still change state afterwards. Prefer ``async``
   code for anything long-running, and make threaded handlers safe to finish late.

Background tasks and server push
--------------------------------

``run_task`` starts an ``async`` function that lives as long as the component::

    class Clock(Component):
        now = State("")

        async def mount(self):
            self.run_task(self.tick)

        async def tick(self):
            while True:
                self.now = datetime.now().strftime("%H:%M:%S")
                await asyncio.sleep(1)

        def render(self):
            return Text(self.now)

Whenever the task changes state, the affected components are re-rendered and the patches are
sent to the browser over a server-sent-events stream (``GET /_rational/stream``). The page opens
the stream only when it has tasks. Details worth knowing:

* The task is cancelled when the component unmounts or the page expires. An open stream keeps the
  page alive; closing the tab lets it expire as usual.
* Changes made before the stream connects are delivered when it does. Bursts of changes are
  coalesced into one batch.
* Every batch has a ``seq`` number. The browser applies pushed and event-driven updates in render
  order, and reloads the page if a reconnect shows it missed some.
* An exception in the task is logged, not shown to the user. Only ``async`` functions are accepted.
* A page may hold at most four open streams (for example, one tab plus reconnects).
* Task code does not hold the session or page locks while it runs, so keep each state change
  small and consistent. Request-scoped helpers such as ``self.context`` refer to the most recent
  event and may be stale; prefer services and ``self.app``.

Loading states and deferred content
-----------------------------------

``Suspense`` sends the page immediately with a fallback and pushes the real content when it is
ready, so one slow query never delays the first paint:

.. code-block:: python

    Suspense(load=self.load_report, fallback=Skeleton(height="12rem"), error=Text("Report unavailable"))

``load`` is a sync or async callable returning anything renderable. It runs as a background task (see
above), so the page becomes interactive and opens the push stream. If ``load`` raises, the exception is
logged and ``error`` is shown. Without JavaScript only the fallback appears, so keep essential content
out of ``Suspense``. ``Skeleton(width=, height=)`` is a shimmering placeholder block.

While an event is in flight the runtime sets ``data-rw-busy`` on ``<html>`` (a thin progress bar
appears after 150 ms) and ``aria-busy="true"`` on the element that triggered it. Both are styleable.

Live sessions across tabs
-------------------------

Session data is shared by every tab of one browser, but a tab only learns about a change the next
time it handles an event. ``App(live_session=True)`` makes it immediate::

    app = App(live_session=True)

    class Cart(Component):
        items = State(0, scope="session")   # or anything read from self.context.session

When one tab changes session data, every other tab of that browser that *rendered* session data
re-renders and receives the patches over the stream, with no click needed. Notes:

* Only pages that read session data open a stream, so the cost is one connection per such tab.
* The tab that made the change is not sent the same update twice.
* It is off by default. Within one process this is immediate; with several workers a change only
  reaches tabs held by the same worker (a shared pub/sub backend is future work).
* Changes made from a plain thread (``@threaded`` handlers) reach other tabs on their next event.
