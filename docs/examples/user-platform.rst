User platform
=============

Real accounts: sign-up with hashed passwords, sign-in, profile settings, roles and an admin area.

.. code-block:: text

   user-platform/
   ├── app.py            # composition root
   ├── settings.py       # DATABASE_URL, session lifetime
   ├── models/           # database.py, user.py, forms.py
   ├── services/         # security.py, auth.py, accounts.py, admin.py
   └── views/
       ├── components/   # shell, account_forms
       ├── pages/        # account.py, admin.py
       └── styles/

1. Passwords
------------

.. literalinclude:: ../../examples/user-platform/services/security.py
   :caption: services/security.py

``hashlib.scrypt`` from the standard library, a random salt per password, and a constant-time
comparison. After signing in, the ``?next=`` target goes through :func:`rational.local_path`, which
refuses anything that is not a path on this site (``//evil.example``, ``/\evil.example`` and the
like), so a crafted link cannot turn the login page into an open redirect.

2. Who is signed in?
--------------------

.. literalinclude:: ../../examples/user-platform/services/auth.py
   :caption: services/auth.py

The session only stores the user id. The authenticator loads the user on every request, so a
role change or a deleted account takes effect immediately. ``app.authenticate(current_user)``
installs it, and ``self.context.user`` / ``self.user`` return its result everywhere.

3. Business rules as field errors
---------------------------------

.. literalinclude:: ../../examples/user-platform/services/accounts.py
   :pyobject: AccountService.register

``FieldError("email", ...)`` shows the message under the email field, just like a validation
error. Sign-in uses one message for "unknown email" and "wrong password", so it doesn't reveal
who has an account.

4. Access control in two places
-------------------------------

.. literalinclude:: ../../examples/user-platform/services/admin.py
   :pyobject: AdminService.require_admin

.. literalinclude:: ../../examples/user-platform/views/pages/admin.py
   :caption: views/pages/admin.py

The page calls ``require_admin`` in ``mount()``, so members get a 403 page, and every service
method checks again, so the API is protected too. The router has a prefix: ``@router.page("/")``
is served at ``/admin``.

5. Composition
--------------

.. literalinclude:: ../../examples/user-platform/app.py
   :caption: app.py
