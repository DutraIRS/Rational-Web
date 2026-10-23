# Ideas: concurrency, reactivity, state, client rendering and serverless

Working notes, not commitments. Each idea says what it builds on, what it costs, and a suggested
order. Current behaviour is described in `docs/running.rst`, `src/rational/protocol.py` and
`src/rational/runtime.py`.

## Status

Implemented: handler timeouts and `@threaded`, background tasks, SSE push and optional WebSocket push,
client navigation, live cross-tab sessions, API-only mode, fine-grained diffs, Suspense, persistent
sessions, optimistic updates (C3), resumable page state via server-side snapshots (D5, the state-token
variant was not built) and a serverless/ASGI guide (D4, documentation only, not tested on the
platforms). Cross-worker live sessions work through `App(bus=)` (Redis bus tested against a fake only);
background-task pushes still reach only the worker holding the stream.
D2 (stateless sessions) is largely covered by `PersistentSessionStore`. The "Where we are" text below
predates this work.

## Where we are

- Every tab gets its own **page runtime** (component tree, handlers, dependency graph). It lives in
  process memory (`app.pages`, a TTL store) and is identified by a page id.
- Reactivity is dependency-tracked: reading a `State` registers the component, writing it marks
  that component dirty, and the next flush re-renders only dirty components into morph patches.
- Events are client-initiated: one `fetch` at a time from a browser queue. The server serializes
  work per session (`Session.lock`) and per page (`PageRuntime.lock`) and rejects stale events
  (`rev` mismatch, HTTP 409).
- Scopes: `component` and `page` state live in the runtime; `session` state lives in the session
  and is shared by all tabs of that browser.
- Tabs of one session see each other's session changes only on their **next event**
  (`refresh_session_state`); nothing is pushed.
- Handlers and renders may be `def` or `async def`. Nothing runs in threads.

## A. Concurrency and reactivity

1. **Run sync handlers off the event loop.** `def` handlers/renders that do I/O block the server.
   Run them with `anyio.to_thread.run_sync`, keep `async def` on the loop, keep the session and
   page locks, and apply state writes under the lock. Opt-in (`@on_thread` or
   `App(sync_handlers="thread")`) so existing apps do not change.
2. **Handler timeouts.** A per-handler (and app-wide default) `timeout=` that cancels the handler
   and returns a clear error, so one stuck handler cannot hold a session lock forever. Small and
   safe; do it first.
3. **Less lock contention.** Today one slow handler blocks every tab of the same session. Hold
   the session lock only around session-state reads/writes (snapshot before, merge after) instead
   of for the whole handler.
4. **Server push (SSE first, WebSocket optional).** An `/_rational/stream` endpoint per page
   runtime that reuses the morph-patch format. Needs reconnect, resume by `rev`, and limits per
   page. Unlocks chat, dashboards and progress bars.
5. **Page-scoped background tasks.** `self.run_task(coro)` cancelled when the page runtime is
   disposed, for polling and long jobs. Today a user's `asyncio.create_task` can outlive the page
   and write to a dead runtime.
6. **Smarter delivery in the browser.** Supersede or cancel an in-flight input request when a
   newer one arrives, optimistic updates for simple inputs, and a visible
   offline/reconnecting state when `fetch` fails.
7. **Multi-worker.** Runtimes are worker-local. Either keep sticky routing and document it, or
   make runtimes rebuildable (see C3).

Suggested order: 2, 1, 5, then 4. Write the concurrency model into `docs/` before any of it.

## B. State management across tabs

Goal: opening several tabs, or several devices, behaves predictably.

Scopes, from narrowest to widest:

| Scope | Lives in | Shared with | Survives reload | Exists today |
| ----- | -------- | ----------- | --------------- | ------------ |
| `component` | page runtime | one component | no | yes |
| `page` | page runtime | one tab | no | yes |
| `client` | browser (`localStorage`) | tabs of one browser, via `BroadcastChannel` | yes | no |
| `session` | session store | all tabs of one browser | yes | yes |
| `user` | database/store | all devices of one account | yes | no |
| `shared` (keyed, for example a room) | store with pub/sub | everyone subscribed | yes | no |

1. **Live session sync across tabs.** The session keeps weak references to its page runtimes.
   When `session.revision` changes, every other runtime marks its session readers dirty, flushes,
   and pushes patches (needs A4). Single process: trivial. Multi-worker: needs a pub/sub backend
   (Redis).
2. **Browser-only `client` scope.** A small state value that never touches the server, persisted
   in `localStorage` and kept in sync between tabs with `BroadcastChannel` (theme, sidebar
   collapsed, draft text). Declared in Python, executed by the existing runtime; no
   Python-to-JavaScript compiler.
3. **`user` and `shared` scopes.** `State(scope="user")` persists per account through a
   pluggable `StateStore` (memory, Redis, SQL). `State(scope="room:{id}")` is keyed and publishes
   change notifications so subscribed pages re-render.
4. **Better conflict handling than reload.** On a stale `rev`, answer 409 together with fresh
   patches for the current state instead of only a reload action, so the user keeps their place.
5. **Per-field merge for forms.** Handlers are already serialized on the server, so real conflicts
   only come from stale views. Last-write-wins per field is enough to start; document it.

## C. Client-side rendering

Non-goal stays: no Python-to-JavaScript compiler. The node IR is already safe, deterministic
and serializable, and the morph engine already runs in the browser, which gives several routes.

1. **Client-side navigation (already on the roadmap).** Fetch the next page's HTML, morph the
   body, update history, prefetch on hover. This is most of the "no full reload" feel for little
   code.
2. **Declarative client actions and local state.** Extend `js.confirm()`-style helpers into a
   small set of actions the browser runs without a server round trip (toggle, show/hide, copy,
   set class, local value). Serialized as data attributes, executed by `runtime.js`.
3. **Optimistic updates.** The handler declares the expected local result; the browser applies it
   immediately and reconciles with the server patches.
4. **Client-rendered islands calling `@remote`.** The runtime already calls
   `/api/<service>/<method>` from the browser. A component whose behaviour is only API calls plus
   a client template needs no page runtime and can be **statically exported** (see D).
5. **Research: the render core in the browser (Pyodide/WASM).** Components, runtime, node IR and
   styling are plain async Python. Splitting the core from the FastAPI/Starlette layer would let
   the same `PageRuntime` run in the browser, with a local event dispatcher instead of HTTP. It is
   heavy (megabytes) and needs a clean core/HTTP split first, so keep it as an experiment, not a
   plan.

Suggested order: C1, C2, C3, then C4 together with D. C5 only after the core is split.

## D. Serverless and stateless deployment

Server-rendered interactivity depends on process memory (runtimes, in-memory sessions), which is
the opposite of serverless. Two complementary directions:

1. **API-only apps.** `App(pages=False)` or an `api_only` mode: services only, no page runtimes,
   no server session. Auth by bearer token or signed cookie. Export OpenAPI and generate typed
   Python and TypeScript clients.
2. **Stateless sessions.** An encrypted, signed cookie session (size-capped) as an alternative to
   a session store, so a function can serve any request.
3. **Static site plus serverless API (JAMstack).** `--export` for the pages (done), `@remote`
   services on a function platform, browser islands calling them (C4). Needs CORS settings, token
   auth and a documented base URL.
4. **ASGI adapters.** Thin documented wrappers for AWS Lambda (Mangum), Cloud Run, Vercel and
   Azure Functions. Watch cold starts (import SQLAlchemy lazily) and database connections (a
   `NullPool` option, connection proxies).
5. **Resumable page state: the key enabler.** Serialize `page`-scope `State` (values must be
   Pydantic-serializable) and rebuild a runtime on demand by re-running `mount()` and restoring
   values. Two storage options:
   - *Server-side store* (Redis/DynamoDB), keyed by page id: small payloads, needs a store.
   - *State token*: signed and encrypted state sent to the browser and returned with each
     event: no server store, but it adds payload size and needs replay protection with `rev`.

   This removes the sticky-routing requirement, lets idle runtimes be evicted safely, survives
   restarts, and makes full interactive pages work on serverless. Cost: state must be
   serializable, and every event pays a load and a store.

Suggested order: D1, D2, D3 (a complete static-plus-API story), then D5 (full interactivity
without sticky workers), then D4 adapters.

## Overall priorities

Status: items 1, the A5/A4 part of item 3, client-side navigation (C1), live session sync (B1),
API-only mode and CORS (D1, D3) are implemented (see the changelog). Stateless signed-cookie
sessions (D2) and resumable page state (D5) are still open.

1. Handler timeouts, thread offload and the concurrency docs (A2, A1).
2. Client-side navigation and declarative client actions (C1, C2).
3. Page background tasks and SSE push (A5, A4), then live cross-tab session sync (B1).
4. API-only mode, stateless sessions and the static-plus-API recipe (D1 to D3).
5. Resumable page state, which unlocks multi-worker and serverless (D5), with `user` and
   `shared` scopes (B3).
6. Defer the WASM core (C5) until there is demand and the core/HTTP split exists.
