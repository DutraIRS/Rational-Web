import pytest

from rational.testing import TestClient


@pytest.fixture
def market(example):
    return example("marketplace")


def cart_count(page) -> str:
    return page.dom.find_all("a", href="/cart")[0].get("aria-label")


def test_search_filter_and_sort(market):
    with TestClient(market.app) as client:
        shop = client.open("/")
        assert "12 products" in shop.text
        shop.input("Search", "key")
        assert "1 product" in shop.text and "Mechanical keyboard" in shop.text
        shop.input("Search", "")
        shop.input("Category", "Books", event="change")
        assert "3 products" in shop.text and "Python in Practice" in shop.text
        shop.input("Sort by", "price-desc", event="change")
        titles = [h.text for h in shop.dom.find_all("h3")]
        assert titles[0] == "Designing Data Systems"
        shop.input("Category", "Not a category", event="change")  # ignored, back to everything
        assert "12 products" in shop.text


def test_cart_updates_everywhere_and_survives_sign_in(market):
    with TestClient(market.app) as client:
        shop = client.open("/")
        assert cart_count(shop) == "Cart, 0 items"
        shop.click("Add Monstera plant to cart")
        assert cart_count(shop) == "Cart, 1 item"  # the header re-rendered by itself
        sold_out = [b for b in shop.dom.find_all("button") if b.get("aria-label") == "Add The Web, Rationally to cart"]
        assert "disabled" in sold_out[0].attrs

        other_tab = client.open("/products/1")
        other_tab.input("Quantity", "2", event="change")
        other_tab.click("Add to cart")
        assert cart_count(other_tab) == "Cart, 3 items"
        shop.input("Search", "plant")  # the first tab catches up on its next interaction
        assert cart_count(shop) == "Cart, 3 items"

        cart = client.open("/cart")
        assert "Pour-over coffee kit" in cart.text and "Monstera plant" in cart.text and "$97.00" in cart.text
        assert "Sign in to check out" in cart.text
        client.open("/login?next=/cart").submit({"name": "ada"})
        cart = client.open("/cart")
        assert "Place order" in cart.text and "$97.00" in cart.text  # the cart is still there


def test_checkout_is_transactional(market):
    with TestClient(market.app) as client:
        client.open("/login").submit({"name": "ada"})
        product = client.open("/products/11")  # the two-person tent: 2 in stock
        product.input("Quantity", "2", event="change")
        product.click("Add to cart")
        cart = client.open("/cart")
        data = cart.submit({"address": "short"})
        assert data["error"]["details"][0]["field"] == "address"
        data = cart.submit({"address": "1 Infinite Loop, Cupertino"})
        assert data["actions"][0]["url"].startswith("/orders?placed=")

        orders = client.open(data["actions"][0]["url"])
        assert "Thank you!" in orders.text and "2 × Two-person tent" in orders.text and "$498.00" in orders.text
        assert "Sold out" in client.open("/products/11").text
        assert "Your cart is empty" in client.open("/cart").text


def test_two_customers_cannot_oversell(market):
    with TestClient(market.app) as ada, TestClient(market.app) as bob:
        carts = []
        for client, name in ((ada, "ada"), (bob, "bob")):
            client.open("/login").submit({"name": name})
            product = client.open("/products/11")
            product.input("Quantity", "2", event="change")
            product.click("Add to cart")
            carts.append(client.open("/cart"))
        ada_cart, bob_cart = carts
        assert ada_cart.submit({"address": "12 Analytical Street"})["actions"]
        data = bob_cart.submit({"address": "34 Compiler Avenue"})
        assert "actions" not in data or not data["actions"]
        assert "Only 0 left of “Two-person tent”" in bob_cart.text
        assert bob.http.get("/api/shop/my-orders").json() == []


def test_api(market):
    with TestClient(market.app) as client:
        books = client.http.get("/api/shop/products", params={"category": "Books", "sort": "price-asc"}).json()
        assert [b["name"] for b in books] == ["The Web, Rationally", "Python in Practice", "Designing Data Systems"]
        assert client.http.get("/api/shop/products", params={"sort": "random"}).status_code == 422
        assert client.http.get("/api/shop/product", params={"product_id": 999}).status_code == 404
        assert client.open("/products/999").status_code == 404
        assert client.http.get("/api/shop/my-orders").status_code == 401
