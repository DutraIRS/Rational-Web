Security model
==============

Rational Web keeps the network boundary explicit and secure by default.

Output
   All text and attribute values are escaped. Tag and attribute names are validated;
   ``<script>``/``<style>`` elements, the ``srcdoc`` attribute, inline ``on*=`` attributes
   and ``javascript:``, ``vbscript:`` and non-image ``data:`` URLs are rejected — both on
   rendered elements and in ``js.set_attr``/``js.toggle_attr``. ``unsafe_html()`` is the only
   way to emit raw markup. CSS values cannot contain ``; { } < >`` or comments.

Events
   The browser can only reference handler ids that were rendered into *its own* page
   view; there is no way to name a Python method. Each event must present the session
   cookie the page view is bound to **and** the session's CSRF token (header). Payloads
   are validated against handler annotations before the handler runs. Unknown handlers
   resynchronize the page instead of failing. Events are size-limited (64 KiB) and
   rate-limited per browser session, whatever the number of its page views. On a page with ``auth="required"``, a visitor who has signed out in
   the meantime is sent to sign in again instead of the handler running.

Requests
   Bodies over ``Limits(max_request_bytes=...)`` (10 MiB) are refused with 413, before they are read
   when the request announces its size and as soon as they pass the limit otherwise. Tampered
   cookies, tokens and headers count as invalid, whatever characters they contain.

Sessions
   The browser only holds an opaque random id (``HttpOnly``, ``SameSite=Lax``, ``Secure``
   over HTTPS). ``session.login()`` and ``session.logout()`` rotate the id and the CSRF
   token, even when the request then fails, and nothing is ever stored under the old id
   after a login. With a persistent store, a logout on one worker ends the session on all of
   them. Session ids are stored hashed, in a persistent store and in page snapshots, so a copy of
   the store holds no usable tokens.

Live page views
   A page view lives in server memory, and anyone can ask for one, so the pools are arranged to keep
   a flood of anonymous requests away from the visitors who use the site. A first-time visitor's
   page views and session wait in a separate, smaller pool until the browser comes back with the
   session cookie; one session holds at most 16 page views (its own oldest goes first); and one IP
   address opens at most 60 page views a minute without a cookie. A persistent store keeps a
   first-time visitor's record for an hour, not a day. Page views expire after 30 idle minutes.
   These are defaults of :class:`~rational.Limits`. They raise the cost of a flood, they do not stop
   one: in production, put a reverse proxy that limits request rates in front, and list it in
   ``FORWARDED_ALLOW_IPS`` so that limits count the visitor's address, not the proxy's.

Passwords and timing
   scrypt with parameters from the OWASP list, on a bounded pool of worker threads. Sign-in and
   account emails take about the same time whether or not the account exists, when you use
   ``averify_password(password, None)`` and :class:`~rational.accounts.Accounts`.

Live connections
   A WebSocket handshake must come from this site or a listed origin. ``auth="required"`` is
   checked again with every message, when the session changes and every 30 seconds, so signing
   out ends the connection. A client that stops reading is disconnected; it cannot slow the others
   or fill the server's memory.

Redirects
   ``Redirect`` refuses ``javascript:``, ``vbscript:`` and ``data:`` targets, and
   ``self.navigate()`` only accepts paths on the site. Pass any target taken from the request
   (a ``?next=`` parameter) through :func:`rational.local_path`, which also refuses the
   ``//host``, ``/\host`` and whitespace forms that browsers turn into another origin.

Remote API
   Nothing is exposed unless decorated with ``@remote``. Inputs and outputs are
   validated by Pydantic. Calls other than ``GET`` must carry the session's CSRF token, and when the
   app signs people in with its own cookie instead of the session, they must still carry the
   ``X-RW-CSRF`` header (``rational.call`` always does), which another site cannot add. Their
   bodies must be JSON. ``auth="required"`` enforces authentication; authorization
   (who may touch *which* row) belongs in your service methods — see ``TodoService._owned``
   in the ``todos`` example. Unexpected exceptions never leak details.

Headers
   ``X-Content-Type-Options: nosniff``, ``Referrer-Policy``, ``X-Frame-Options`` and,
   with ``App(csp=True)``, a ``Content-Security-Policy`` that allows no inline script at all:
   scripts must come from the site itself (``script-src 'self'``) and styles carry a per-response
   nonce. Any file the site serves can run as a script, so never serve uploads from an
   ``app.static`` folder on the same origin. Other origins your pages need go in
   ``app.csp_sources``, by directive.

Development mode
   Shows source code and tracebacks. It binds to localhost by default and warns when it
   doesn't. Never run ``--dev`` on a public server.

Reporting vulnerabilities
   See ``SECURITY.md`` in the repository.
