Testing your app
================

:mod:`rational.testing` drives pages through the real HTTP endpoints — cookies, CSRF,
validation and patches included — without a browser. Install the ``testing`` extra.

.. code-block:: python

   from rational.testing import TestClient
   from myapp import app

   def test_counter():
       page = TestClient(app).open("/")
       page.click("Increment")                 # finds the element by its text
       assert "Count: 1" in page.text

   def test_signup_validation():
       page = TestClient(app).open("/signup")
       data = page.submit({"email": "not-an-email"})
       assert data["error"]["code"] == "validation_error"

``PageView`` helpers: ``click(text)``, ``input(label, value, event="input")``,
``submit(data)``, ``fire(handler_id, payload)``, ``field(label)``, ``text``, ``html`` and
``dom`` (a small queryable tree). Use ``with TestClient(app) as client:`` when the app
has startup hooks (for example creating database tables).

For real-browser tests, the project's own suite uses Playwright
(``pip install "rational[browser]"``); see ``tests/browser``.
