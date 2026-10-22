# Examples

Ten complete applications, from a single page to a social network. Each one has its own README,
and the documentation walks through every example file by file.

| Example | What it is | What you'll learn |
|---|---|---|
| [hello](hello/) | The smallest app: one static page | Pages, primitives, zero-JS output |
| [counter](counter/) | The specification's counter | State, keys, events, debounced input |
| [media](media/) | Images, links and embeds | Favicons, local/remote assets, video, PDFs, the `h()` escape hatch |
| [dashboard](dashboard/) | A responsive analytics dashboard | Breakpoints, container queries, fluid grids |
| [cv-portfolio](cv-portfolio/) | A one-page CV and portfolio | Content as data, function components, honeypot forms |
| [todos](todos/) | Multi-user todo lists | Databases, services, per-user isolation, the JSON API |
| [blog](blog/) | A blog with an editor | Path parameters, safe rich text, live preview, RSS |
| [user-platform](user-platform/) | Accounts, roles and an admin area | Password hashing, authenticators, `FieldError`, access control |
| [marketplace](marketplace/) | A shop with a cart and checkout | Session state, transactions, money, overselling |
| [social-network](social-network/) | Posts, likes, follows and timelines | Relational queries without N+1, local updates |

## Running an example

```console
$ pip install "rational[db]"
$ cd examples/marketplace
$ python app.py --dev       # hot reload, live browser reload, readable errors
$ python app.py --prod      # production server
```

Database examples create their SQLite file next to `app.py`. Set `DATABASE_URL` to use another
database. Apps with services publish interactive API docs (Swagger UI) at `/api/docs`.

## Project layout

Every example except `hello` is laid out like a real project:

```
example/
├── README.md          # what it shows and how to run it
├── app.py             # the composition root: App + routers + services + startup hooks
├── settings.py        # settings from the environment
├── models/            # database.py (engine + base), one file per table group
├── services/          # business rules (+ the JSON API)
└── views/
    ├── styles/        # theme and shared styles
    ├── components/    # reusable components
    └── pages/         # pages, declared on Routers
```

Pages are declared on a `rational.Router`, so page modules never import the app. `app.py` is the
only place that knows how the parts fit together.

## Tests

Every example is covered by the test suite in [`tests/examples`](../tests/examples), which is also a
good place to see how to test an app with `rational.testing.TestClient`.
