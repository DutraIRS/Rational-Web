# Dashboard

A responsive analytics dashboard with **zero hand-written CSS or JavaScript**.

```
dashboard/
├── app.py                     # composition root
├── models/
│   └── metrics.py             # Metrics, Order, the periods
├── services/
│   └── metrics.py             # MetricsService: the numbers (+ GET /api/metrics/overview)
└── views/
    ├── styles/
    │   ├── theme.py           # the theme preset
    │   ├── layout.py          # sidebar and main area, with breakpoints
    │   └── data.py            # tables and the bar chart, with a container query
    ├── components/
    │   ├── sidebar.py
    │   ├── stat_card.py
    │   ├── region_chart.py
    │   └── recent_orders.py
    └── pages/
        └── overview.py        # the dashboard page
```

## What it shows

- **Viewport breakpoints:** `Row(collapse="narrow")` stacks the sidebar above the content below 1024px,
  and its links become a compact row.
- **Fluid grids:** `Grid(min_column_width=200)` fits as many columns as the space allows, with no media queries.
- **Container queries:** the chart hides its amounts when *its card* is narrow, whatever the screen size.
- **Styles as a layer:** every `Style` lives in `views/styles/`; components just reference them.
- **Server events:** changing the range or pressing Refresh re-renders only what changed.
- **Browser-only operations:** the theme buttons use `js.set_theme(...)`, with no round trip.
- **Never trust the browser:** the page ignores ranges that are not offered, and the API rejects them.

## Run it

```console
$ cd examples/dashboard
$ python app.py --dev
```

Resize the window, or open it on a phone, to see the layout adapt. The same numbers are available
as JSON at http://127.0.0.1:8000/api/metrics/overview?days=7.
