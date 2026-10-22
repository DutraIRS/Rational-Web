# Marketplace

A small shop: a searchable catalog, a cart that follows you across pages and tabs, a checkout that
can't oversell, and order history.

```
marketplace/
├── app.py                    # composition root: App, pages, service, startup hooks
├── settings.py               # settings from the environment (DATABASE_URL)
├── models/
│   ├── database.py           # engine + declarative base
│   ├── product.py            # the Product table, ProductOut, sort options
│   ├── order.py              # Order, OrderLine (prices copied), OrderOut, CheckoutForm
│   ├── money.py              # integer cents -> "$12.90"
│   └── account.py            # the sign-in form
├── services/
│   ├── shop.py               # ShopService: search, checkout transaction, orders (+ JSON API)
│   └── seed.py               # the demo catalog
└── views/
    ├── styles/
    │   ├── theme.py          # the brand: the modern preset with the shop's orange
    │   ├── layout.py         # header and page frame
    │   ├── catalog.py        # product tiles
    │   └── cart.py           # cart lines and summary
    ├── components/
    │   ├── cart.py           # CartAware: the session-scoped cart, as a mixin
    │   ├── header.py         # brand, navigation, live cart count
    │   ├── shell.py          # page layout
    │   └── product_card.py   # product tile with stock badge and "Add to cart"
    └── pages/
        ├── catalog.py        # / (search, category, sort) and /products/{product_id}
        ├── checkout.py       # /cart
        └── account.py        # /login and /orders
```

## What it shows

- **A brand theme:** `views/styles/theme.py` customizes a preset with `with_colors(...)`, for light and dark.
- **Session-scoped state:** the cart is `State(scope="session")` on a mixin. Every component that
  inherits `CartAware` shares it, and the header's count updates the moment a card adds a product.
  Other tabs catch up on their next interaction.
- **Search as you type:** a debounced `on_input` runs a real query with bound parameters.
- **A checkout that can't oversell:** stock is checked and decremented in one transaction; if someone
  else bought the last item, the order is rolled back and the cart explains why.
- **Money as integer cents** and order lines that copy name and price, so history never changes.
- **No N+1 queries:** relationships use `lazy="raise"`, and orders load their lines with `selectinload`.
- **The cart survives sign-in:** `session.login()` rotates the session id (against session fixation)
  but keeps the session's data.

## Run it

```console
$ pip install "rational[db]"
$ cd examples/marketplace
$ python app.py --dev
```

Try opening the shop in two tabs, add items in one, then interact with the other.
