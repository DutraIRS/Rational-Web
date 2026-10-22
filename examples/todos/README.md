# Todos

A multi-user todo list: SQLAlchemy persistence, sign-in, a service that is also a REST API,
and strict per-user isolation.

```
todos/
├── app.py                 # composition root: App + pages + service + startup hook
├── settings.py            # settings from the environment (DATABASE_URL)
├── models/
│   ├── database.py        # engine + declarative base
│   ├── todo.py            # the Todo table, TodoOut, NewTodo
│   └── account.py         # the sign-in form
├── services/
│   └── todos.py           # TodoService: every query, ownership checks, @remote API
└── views/
    ├── styles/            # theme, page layout, list styles
    ├── components/
    │   └── todo_item.py   # one row
    └── pages/
        ├── todos.py       # the list (signed-in users only)
        └── login.py       # the demo sign-in
```

## What it shows

- One service powers the pages *and* the JSON API (`/api/todo/...`, Swagger UI at `/api/docs`).
- Ownership is checked in the service: another user's todo is "not found", over the UI or the API.
- Forms validate against Pydantic models; a new `key=` on the form resets it after adding.
- `js.confirm()` asks before deleting, in the browser.
- `auth="required"` redirects anonymous visitors to `/login`.

## Run it

```console
$ pip install "rational[db]"
$ cd examples/todos
$ python app.py --dev
```

The database (`todos.db`) is created next to `app.py`. Set `DATABASE_URL` to use another one.
