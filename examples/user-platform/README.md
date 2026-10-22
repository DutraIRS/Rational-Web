# User platform

Real accounts: sign-up with hashed passwords, sign-in, profile settings, roles and an admin area.

```
user-platform/
├── app.py                     # composition root: App, authenticator, pages, services
├── settings.py                # settings from the environment (DATABASE_URL)
├── models/
│   ├── database.py            # engine + declarative base
│   ├── user.py                # the User table, UserOut (no password hash!), roles
│   └── forms.py               # sign-up, sign-in, profile and password forms
├── services/
│   ├── security.py            # scrypt password hashing, safe redirects
│   ├── auth.py                # current_user: loads the signed-in user per request
│   ├── accounts.py            # AccountService (+ JSON API)
│   └── admin.py               # AdminService (+ JSON API)
└── views/
    ├── styles/                # theme, page frame, the users table
    ├── components/
    │   ├── shell.py           # header, navigation, account menu
    │   └── account_forms.py   # profile and password forms
    └── pages/
        ├── account.py         # /, /signup, /login, /settings
        └── admin.py           # /admin (a Router with a prefix)
```

## What it shows

- **Passwords done right:** `hashlib.scrypt` from the standard library, a random salt per password,
  constant-time comparison, and one error message for "wrong email" and "wrong password".
- **A custom authenticator:** `app.authenticate(current_user)` loads the user from the database on every
  request, so a role change or a deleted account takes effect immediately.
- **`FieldError`:** business rules ("this email is already registered", "that is not your current
  password") appear under the right field, like type validation errors do.
- **Access control:** `auth="required"` redirects to `/login?next=...`; the admin page raises `Forbidden`
  for members, and the API checks the role too.
- **Safe redirects:** `?next=` only accepts same-site paths.
- **`js.confirm()`** asks before deleting an account, in the browser.
- **Routers with prefixes:** `views/pages/admin.py` declares `Router(prefix="/admin")`.

The first account to sign up becomes an administrator.

## Run it

```console
$ pip install "rational[db]"
$ cd examples/user-platform
$ python app.py --dev
```

Then try the API in Swagger UI at http://127.0.0.1:8000/api/docs while signed in.
