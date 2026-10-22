# Hello

The smallest Rational Web app: one themed, server-rendered page in a single file.

This is the only example that isn't split into a project, on purpose: it shows the least you
need. Every other example uses the project layout described in [the examples overview](../README.md).

## What it shows

- `App`, `@app.page`, and primitives such as `Container`, `Card`, `Heading` and `Text`.
- A page without event handlers ships **no JavaScript**: view the source, there is no `<script>`.

## Run it

```console
$ python examples/hello/app.py --dev
```
