# Counter

The specification's counter, plus the interaction patterns you use every day.

```
counter/
├── app.py                  # composition root: App + pages
└── views/
    ├── styles/             # the theme and shared styles
    ├── components/
    │   ├── counter.py      # Counter: props + state
    │   └── greeter.py      # Greeter: debounced input
    └── pages/
        └── home.py         # the page, declared on a Router
```

This app has no data or business rules, so it only has a `views/` layer. The larger examples
add `models/` and `services/`.

## What it shows

- `State` belongs to each component instance: the two counters are independent.
- `key=` gives each counter a stable identity, so its state survives re-renders.
- `Input(on_input=...)` sends the debounced value to a handler annotated `value: str`.
- `js.toggle_theme()` runs in the browser, with no server round trip.

## Run it

```console
$ cd examples/counter
$ python app.py --dev
```

Open http://127.0.0.1:8000.
