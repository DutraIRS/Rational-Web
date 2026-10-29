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

Sign in with Google, GitHub or Microsoft
----------------------------------------

:class:`~rational.oauth.OAuth` adds sign-in through other providers, ending in ``session.login``::

    from rational.oauth import OAuth, github, google, microsoft

    async def on_login(context, person):        # an OAuthUser: id, email, email_verified, name, ...
        if not person.email_verified:
            return None                          # refuse
        user = await find_or_create_user(person.email, name=person.name)
        return user.id                           # what session.login stores

    oauth = OAuth(app, base_url="https://shop.example", on_login=on_login)
    oauth.add(google(client_id=GOOGLE_ID, client_secret=GOOGLE_SECRET))
    oauth.add(github(client_id=GITHUB_ID, client_secret=GITHUB_SECRET))

    ButtonLink("Sign in with Google", href=oauth.login_url("google", next="/orders"))

Register ``https://shop.example/auth/<provider>/callback`` as the redirect URI with each provider.
Every sign-in carries a one-time ``state`` kept in the session (so another site cannot complete a
sign-in for you), a nonce and a PKCE challenge, and the person's identity is fetched from the
provider over HTTPS. ``next`` only accepts paths on this site. ``microsoft(tenant=...)`` covers
Microsoft accounts and Entra ID; ``oidc(name, issuer, ...)`` any OpenID Connect provider (Okta,
Auth0, Keycloak, GitLab, ...). GitHub gives the verified primary email.

Sign in with Apple
'''''''''''''''''''

Apple deviates from the redirect flow: the answer arrives as a signed form POST, the client
secret is a JWT signed with a Services ID key for every token request, and there is no userinfo
endpoint — the identity comes from the ID token::

    from rational.oauth import apple

    oauth.add(apple(
        client_id="com.example.web",          # the Services ID
        team_id="TEAM123",
        key_id="KEY1",
        private_key=APPLE_KEY_PEM,            # the .p8 contents
    ))                                        # needs: pip install "rational[crypto]"

Apple sends the person's name only on the first sign-in, as a form field; ``OAuthUser.name``
carries it then. Afterwards only the stable ``sub`` and (relay) email remain.

Taking payments with Stripe
---------------------------

:class:`~rational.stripe.Stripe` covers Checkout, the customer portal and webhooks, talking to
the REST API directly (``pip install`` nothing extra)::

    from rational.stripe import Stripe

    stripe = Stripe(app, secret_key=STRIPE_SECRET_KEY, webhook_secret=STRIPE_WEBHOOK_SECRET)

    ButtonLink("Upgrade", href=stripe.checkout_url(     # a signed link; Stripe is called on click
        line_items=[{"price": "price_123", "quantity": 1}],
        mode="payment",                                  # or "subscription"
        success_url="/done?session_id={CHECKOUT_SESSION_ID}",
        cancel_url="/upgrade",
    ))

    @stripe.handler
    async def on_stripe(event):                          # only verified events reach here
        if event["type"] == "checkout.session.completed":
            ...

``stripe.checkout_url`` signs the parameters, so nothing is sent to Stripe while the page
renders and the link cannot be altered. ``stripe.portal(customer_id, return_url=...)`` opens the
customer portal. Webhook handlers run only after the ``Stripe-Signature`` header is checked
against the raw request body, with a five-minute replay window. Point Stripe at
``https://shop.example/stripe/webhook``.

Password recovery, email verification and sign-in links
--------------------------------------------------------

:class:`~rational.accounts.Accounts` sends the account emails every site needs. Subclass it with
the lookups your user model needs; everything else (signed, expiring links, the messages, the
checks) is done for you::

    from rational.accounts import Accounts

    class ShopAccounts(Accounts):
        async def find(self, email):                       # the user with this address, or None
            return (await users.find(User.email == email.lower(), limit=1) or [None])[0]

        async def get(self, user_id):                      # the user with this id, or None
            return await users.get(int(user_id))

        async def save_password(self, user, password_hash):
            await users.update(user.id, password=password_hash)

        async def mark_verified(self, user):
            await users.update(user.id, verified=True)

    accounts = ShopAccounts(app, mailer, base_url="https://shop.example", store=jobs.store)

Then, from your pages and services:

* ``await accounts.send_reset(email)`` emails a link to ``/reset-password?token=...``, where
  ``await accounts.reset(token, new_password)`` sets the new password. The link is tied to the old
  password, so it works once, for an hour.
* ``await accounts.send_verification(user)`` and ``await accounts.verify(token)`` confirm an
  address (the link stops working if the address changes).
* ``await accounts.send_sign_in_link(email)`` and ``user = await accounts.sign_in(token)`` sign in
  without a password: the link works once, for 15 minutes. Follow it with
  ``session.login(accounts.user_id(user))``.

A bad, expired or used link raises :class:`~rational.security.InvalidToken`; a too-short password
raises ``FieldError("password", ...)``. The ``send_*`` methods behave the same whether or not the
address has an account, so they cannot be used to find out who is registered, and send at most one
message per address and purpose a minute. Give the mailer ``jobs=`` so that sending takes the same
short time either way, and pass ``store=jobs.store`` when the app runs on several workers.
Paths, lifetimes and the minimum password length are class attributes; override
``reset_message``, ``verify_message`` and ``sign_in_message`` to change the wording or translate it.

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

Keeping bots out
----------------

Three tools from :mod:`rational.bots`, from least to most friction for people:

**Rate limits.** ``@limit("5/minute")`` caps how often one client may call an event handler, a
``@remote`` method or load a page (on the ``Page`` class). Past the limit the caller gets HTTP 429
with ``retry_after``. ``per="ip"`` (default), ``"user"`` (the signed-in user, else the IP) or
``"session"``. Rates read ``"100/hour"`` or ``"10/15 minutes"``. Counts live in memory; on several
workers, share them: ``app.limiter = Limiter(RedisSessionDriver(url=...))``.

**Form checks.** Put :class:`~rational.bots.HumanCheck` in a form and ``@human`` on its submit
handler::

    from rational.bots import HumanCheck, human, limit

    class Signup(Component):
        @human
        @limit("10/hour")
        async def create(self, form: SignupForm):
            ...

        def render(self):
            return Form(Input("Email", name="email"), HumanCheck(),
                        Button("Sign up", type="submit"), on_submit=self.create)

``HumanCheck`` adds a field people never see but form-filling bots do, and the signed time the
form was shown. ``@human`` refuses a submit that fills the trap, comes faster than
``app.min_form_seconds`` (2 s) or lacks the fields; the handler never sees them.

**CAPTCHA.** For forms under real attack, add a challenge to every ``HumanCheck``::

    from rational.bots import Captcha

    Captcha(app, "turnstile", site_key=SITE_KEY, secret=SECRET_KEY)   # or "hcaptcha", "recaptcha"

Cloudflare Turnstile is free and asks most people nothing. The widget's script and frames are
added to the pages and to the Content-Security-Policy, and ``@human`` checks the answer with the
provider before the handler runs; a missing or wrong answer is shown under the form as a
``captcha`` field error. Widgets render when the page loads, so keep a CAPTCHA form on a page of
its own rather than revealing it later.

Search engines and link previews
--------------------------------

:class:`~rational.seo.Seo` gives every page what search engines and link previews read, and
serves ``/sitemap.xml`` and ``/robots.txt``::

    from rational.seo import Seo, structured

    Seo(app, site_url="https://shop.example", site_name="Shop", image="/assets/preview.png",
        twitter="@shop", disallow=["/admin"])

    @app.page("/{lang}/products/{slug}.html", paths=PRODUCT_PATHS)
    class Product(Page):
        slug: str

        def mount(self):
            self.product = load_product(self.lang, self.slug)
            self.title = self.product.name
            self.description = self.product.summary
            self.image = self.product.photo_url
            self.alternates = {lang: f"/{lang}/products/{self.slug}.html" for lang in LANGUAGES}
            self.structured_data = structured("Product", name=self.product.name)

* Each page gets a canonical URL (``canonical`` overrides it), Open Graph and Twitter tags from its
  ``title``, ``description`` and ``image``, ``hreflang`` links from ``alternates`` and its
  ``structured_data`` as JSON-LD. ``noindex = True`` asks search engines to leave a page out.
* ``/sitemap.xml`` lists every page anyone may see: not ``noindex`` pages or pages that need
  sign-in, and parameter routes through their ``paths=``. A static export writes both files.
* A ``{lang}`` path parameter sets the page's language (``<html lang>``), so translated sites need
  no extra prop.

Background jobs
---------------

Work that should not hold up a request (emails, reports, calls to slow services) goes to a job.
:class:`~rational.jobs.Jobs` runs them on workers inside the app's processes, retrying failures
with growing delays::

    from rational.jobs import Jobs, RedisJobStore

    jobs = Jobs(app)                          # in memory: lost on restart, one process
    jobs = Jobs(app, store=RedisJobStore(url="redis://localhost:6379/0"))  # shared, kept

    @jobs.job(retries=5)
    async def send_receipt(order_id: int) -> None:
        ...

    await send_receipt.enqueue(42)            # returns at once
    await send_receipt.enqueue_in(3600, 42)   # in an hour

    @jobs.every(hours=24)                     # once a day (midnight UTC), on one worker
    async def purge_old_carts() -> None:
        ...

Arguments are stored as JSON (numbers, strings, lists, dicts, Pydantic models) and validated
against the function's annotations when the job runs; wrong arguments fail at ``enqueue``.
A plain ``def`` job runs in a worker thread. Delivery is *at least once*: a job cut off by a crash
or a deploy runs again after its lease (5 minutes by default), so a job should be safe to run
twice. In tests, ``await jobs.run_pending()`` runs everything that is due, right away.

Email
-----

:class:`~rational.mail.Mailer` sends messages written as components, through SMTP or an email
API::

    from rational.mail import SMTP, Mailer

    mailer = Mailer(app, SMTP("smtp.example.com", username=USER, password=PASSWORD),
                    sender="Shop <hello@shop.example>", jobs=jobs)

    class Receipt(Component):
        order: Order

        def render(self):
            return Column(Heading("Thanks for your order"), Text(f"Total: {self.order.total}"), gap="md")

    await mailer.send(customer.email, "Your receipt", Receipt(order=order))

* Email clients ignore stylesheets and CSS variables, so each element's ``Style`` is written into
  its ``style`` attribute with the theme's (light) colors and sizes filled in. Hover and
  responsive variants are left out. A string body is sent as it is (trusted HTML).
* A plain-text version is made from the HTML (paragraphs, lists, link addresses), or pass ``text=``.
* Backends: ``SMTP`` (``security="starttls"``, ``"tls"`` or ``"none"``), ``Resend(api_key)``,
  ``Postmark(server_token)``; ``Console()`` logs messages instead of sending them (development)
  and ``Memory()`` keeps them in ``.outbox`` (tests).
* With ``jobs=``, ``send`` queues the message and returns; delivery is retried up to five times.
  Without it, ``send`` waits for the server and raises if it fails.
* Line breaks in addresses and subjects are refused, so a form value cannot add headers.
