Marketplace
===========

A shop: a searchable catalog, a cart that follows you across pages and tabs, a checkout that
can't oversell, and order history.

.. code-block:: text

   marketplace/
   ├── app.py            # composition root
   ├── settings.py       # DATABASE_URL, shop name
   ├── models/           # database.py, product.py, order.py, account.py, money.py
   ├── services/         # shop.py (ShopService), seed.py
   └── views/
       ├── components/   # cart.py (CartAware), header, shell, product_card
       ├── pages/        # catalog.py, checkout.py, account.py
       └── styles/

1. Money and history
--------------------

.. literalinclude:: ../../examples/marketplace/models/money.py
   :caption: models/money.py

Prices are integer cents. Order lines copy the product's name and price, so an order never
changes when the catalog does. ``lazy="raise"`` turns an accidental lazy load (the N+1 query
problem) into an immediate error.

2. A cart in the session
------------------------

.. literalinclude:: ../../examples/marketplace/views/components/cart.py
   :pyobject: CartAware

``State(scope="session")`` lives in the browser session on the server, shared by every
component that inherits ``CartAware``: the header, the product cards, the cart page. When a card
adds a product, the header's count updates in the same response. Other tabs catch up on their
next interaction.

.. literalinclude:: ../../examples/marketplace/views/components/header.py
   :pyobject: ShopHeader

3. Search as you type
---------------------

.. literalinclude:: ../../examples/marketplace/views/pages/catalog.py
   :pyobject: Catalog

4. A checkout that can't oversell
---------------------------------

.. literalinclude:: ../../examples/marketplace/services/shop.py
   :pyobject: ShopService.checkout

Stock is checked and decremented inside one transaction. If any line fails, *nothing* is
written. The cart page turns that ``RemoteError`` into a friendly message:

.. literalinclude:: ../../examples/marketplace/views/pages/checkout.py
   :pyobject: CartPage.place_order
