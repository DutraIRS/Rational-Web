Auth, cookies, data and live connections
========================================

The pieces most apps need, built in, with safe defaults. None of them needs a package beyond
Rational itself, except encryption (``pip install "rational[crypto]"``).

Signing people in
-----------------

Passwords are hashed with scrypt and a random salt; store the hash, never the password::

    from rational.security import hash_password, verify_password

    user.password = hash_password(form.password)
    ...
    if not verify_password(form.password, user.password):
        raise FieldError("password", "Wrong email or password")
    self.context.session.login(user.id)      # new session id, against session fixation

``session.login(user_id)`` and ``session.logout()`` are all a browser app needs: the session cookie is
``HttpOnly``, and every event and API call is CSRF-checked. ``auth="required"`` on a page or a
``@remote`` method refuses anonymous visitors. To load the user object once per request, install an
authenticator::

    @app.authenticate
    async def current_user(ctx):
        user_id = ctx.session.get("rw.user") if ctx.peek_session() else None
        return await Repository(ctx.db, User).get(user_id) if user_id else None

API clients and JSON Web Tokens
-------------------------------

Mobile apps and other servers send a bearer token instead of a cookie. :class:`~rational.security.Tokens`
issues and verifies JWTs (HS256, with expiry and issuer checks; the token cannot choose its own
algorithm)::

    from rational.security import Tokens

    tokens = Tokens(SECRET, issuer="shop", ttl=3600)
    app.authenticate(tokens.authenticator(lambda claims: load_user(claims["sub"])))

    @app.service
    class Auth(Service):
        @remote()
        async def token(self, email: str, password: str) -> dict:
            user = await check_credentials(email, password)
            return {"token": tokens.issue(str(user.id), role=user.role)}

Requests with ``Authorization: Bearer <token>`` are then signed in as that user; requests without one
fall back to the session.

Secrets
-------

Signed and encrypted values need a long random secret: ``App(secret_key=...)`` or the
``RATIONAL_SECRET_KEY`` environment variable. Make one with
``python -c "import secrets; print(secrets.token_urlsafe(32))"``. In ``--dev`` a temporary one is
made up if none is set; in production the app refuses to sign without one.

:class:`~rational.security.Signer` makes values tamper-proof (readable, not changeable), optionally
expiring: links in emails, unsubscribe tokens. :class:`~rational.security.Box` encrypts values the
client may hold but not read (AES-256-GCM).

Cookies
-------

``self.context.cookies`` reads the request's cookies and sets the response's, in components, pages
and services alike::

    cookies = self.context.cookies
    cookies.set("last_tab", "billing")                        # plain text
    cookies.set("cart", {"items": [3, 7]}, signed=True)       # readable, not changeable
    cookies.set("draft", {"secret": 1}, encrypted=True)       # neither readable nor changeable
    cart = cookies.get("cart", signed=True, default={"items": []})
    cookies.delete("last_tab")

Defaults: ``HttpOnly``, ``SameSite=Lax``, ``Secure`` over HTTPS. A forged or tampered signed cookie
reads as missing. The framework's own cookies (``rw_sid``, ``rw_theme``, ``rw_lang``) cannot be
overwritten by accident.

Data
----

``App(database="postgresql+asyncpg://...")`` gives services ``self.db``. Use SQLAlchemy directly
(``async with self.db.transaction() as s: ...``), or :class:`~rational.backend.database.Repository`
for the everyday operations::

    notes = Repository(self.db, Note)
    note = await notes.add(title="Hi", owner_id=self.user.id)
    page = await notes.page(Note.owner_id == self.user.id, page=2, size=20, order_by=Note.id.desc())
    # page.items, page.total, page.pages
    await notes.update(note.id, title="Hello")
    await notes.delete(note.id)

Migrations: ``rational db init``, ``rational db revision app.py -m "add notes" --autogenerate``,
``rational db upgrade app.py`` (see :doc:`running`).

Sessions
--------

``self.context.session`` is a dict that survives between requests of one browser. It lives in memory
by default; give the app a persistent store for several workers and restarts (see :doc:`running`).

Live connections
----------------

For chat, notifications or collaborative views, a :class:`~rational.Socket` class answers WebSocket
connections. Messages are JSON, validated against ``receive``'s annotation::

    class Say(BaseModel):
        text: str

    @app.socket("/ws/chat")
    class Chat(Socket):
        auth = "required"

        async def connect(self) -> None:
            await self.join("lobby")

        async def receive(self, message: Say) -> None:
            await self.publish("lobby", {"from": self.user.name, "text": message.text})

Each connection must come from this site (or a listed ``origins``), carries the visitor's session,
and is size- and rate-limited (``max_message_bytes``, ``burst``, ``rate``). ``publish()`` reaches the
room on every worker when the app has a bus (``App(bus=RedisBus(...))``). Raising a ``FieldError`` or
``RemoteError`` in ``receive`` sends ``{"error": ...}`` back to that connection.

Pages do not need sockets to stay live: server push for pages is built in (see :doc:`concurrency`).
