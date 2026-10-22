Security model
==============

Rational Web keeps the network boundary explicit and secure by default.

Output
   All text and attribute values are escaped. Tag and attribute names are validated;
   ``<script>``/``<style>`` elements, inline ``on*=`` attributes and ``javascript:``,
   ``vbscript:`` and non-image ``data:`` URLs are rejected. ``unsafe_html()`` is the only
   way to emit raw markup. CSS values cannot contain ``; { } < >`` or comments.

Events
   The browser can only reference handler ids that were rendered into *its own* page
   view; there is no way to name a Python method. Each event must present the session
   cookie the page view is bound to **and** the session's CSRF token (header). Payloads
   are validated against handler annotations before the handler runs. Unknown handlers
   resynchronize the page instead of failing. Events are size-limited (64 KiB) and
   rate-limited per page view.

Sessions
   The browser only holds an opaque random id (``HttpOnly``, ``SameSite=Lax``, ``Secure``
   over HTTPS). ``session.login()`` and ``session.logout()`` rotate the id and the CSRF
   token. Page views expire after 30 idle minutes and are bounded in number.

Remote API
   Nothing is exposed unless decorated with ``@remote``. Inputs and outputs are
   validated by Pydantic. ``auth="required"`` enforces authentication; authorization
   (who may touch *which* row) belongs in your service methods — see ``TodoService._owned``
   in the ``todos`` example. Unexpected exceptions never leak details.

Headers
   ``X-Content-Type-Options: nosniff``, ``Referrer-Policy``, ``X-Frame-Options`` and,
   with ``App(csp=True)``, a nonce-based ``Content-Security-Policy``.

Development mode
   Shows source code and tracebacks. It binds to localhost by default and warns when it
   doesn't. Never run ``--dev`` on a public server.

Reporting vulnerabilities
   See ``SECURITY.md`` in the repository.
