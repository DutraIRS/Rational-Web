"""The cart lives in the browser session, on the server.

``scope="session"`` state is shared by every component that inherits ``CartAware``, on every page
and in every tab of the same browser. Changing it re-renders the components that read it: adding a
product updates the header's count at once; other open tabs catch up on their next interaction.
"""

from rational import Component, State

from models import ProductOut


class CartAware(Component):
    """Mix into any component that reads or changes the cart."""

    cart = State(factory=dict, scope="session")  # {"<product id>": quantity}

    @property
    def item_count(self) -> int:
        return sum(self.cart.values())

    def quantity(self, product_id: int) -> int:
        return self.cart.get(str(product_id), 0)

    def set_quantity(self, product: ProductOut, quantity: int) -> None:
        cart = dict(self.cart)  # reassign a new dict: in-place changes would not be noticed
        quantity = max(0, min(quantity, product.stock))
        if quantity:
            cart[str(product.id)] = quantity
        else:
            cart.pop(str(product.id), None)
        self.cart = cart

    def add(self, product: ProductOut, quantity: int = 1) -> None:
        self.set_quantity(product, self.quantity(product.id) + quantity)

    def empty_cart(self) -> None:
        self.cart = {}

    def cart_items(self) -> dict[int, int]:
        return {int(product_id): quantity for product_id, quantity in self.cart.items()}
