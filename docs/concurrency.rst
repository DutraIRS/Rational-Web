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
