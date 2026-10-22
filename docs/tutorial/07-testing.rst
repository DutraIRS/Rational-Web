7. Testing
==========

:mod:`rational.testing` drives your pages through the real HTTP endpoints (sessions, CSRF,
validation, patches) without a browser. Install the ``testing`` extra and pytest.

.. literalinclude:: guestbook/tests/conftest.py
   :caption: tests/conftest.py

.. literalinclude:: guestbook/tests/test_guestbook.py
   :caption: tests/test_guestbook.py

.. code-block:: console

   $ pytest
   ....                                                    [100%]

What you can do with a page
---------------------------

``page.click("♥ 0")``
   Finds the element handling clicks whose accessible name (``aria-label``, or its text)
   contains the text, and fires the event.
``page.input("Your name", "Ada")``
   Types into the control labelled "Your name".
``page.submit({...})``
   Submits a form with the given fields.
``page.text`` / ``page.html`` / ``page.dom``
   The page after every patch so far.

Each action returns the server's JSON response, so you can also assert on validation errors
or navigation. Use ``with TestClient(app)`` when the app has startup hooks, such as creating
tables.

Next: :doc:`08-deploying`.
