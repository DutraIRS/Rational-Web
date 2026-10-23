import json

import pytest

from rational import App, Button, I18n, Page, Text, js
from rational.testing import TestClient

CATALOGS = {
    "en": {
        "hello": "Hello, {name}!",
        "items.one": "{count} item",
        "items.other": "{count} items",
        "only_en": "English",
    },
    "pt": {"hello": "Olá, {name}!", "items.one": "{count} item", "items.other": "{count} itens"},
}


def make_app():
    app = App(i18n=I18n(CATALOGS))

    @app.page("/")
    class Home(Page):
        def render(self):
            return Text(self.t("hello", name="Ada") + " " + self.t("items", count=2) + " " + self.t("only_en"))

    return app


def test_translate_params_plurals_and_fallbacks():
    i18n = I18n(CATALOGS)
    assert i18n.translate("pt", "hello", name="Ada") == "Olá, Ada!"
    assert i18n.translate("pt", "items", count=1) == "1 item"
    assert i18n.translate("pt", "items", count=5) == "5 itens"
    assert i18n.translate("pt-br", "only_en") == "English"  # falls back to the default catalog
    assert i18n.translate("en", "missing.key") == "missing.key"
    assert i18n.translate("en", "hello") == "Hello, {name}!"  # missing params stay visible


def test_negotiation_order_and_quality():
    i18n = I18n(CATALOGS)
    assert i18n.negotiate("pt", "en") == "pt"  # the cookie wins
    assert i18n.negotiate(None, "fr;q=0.9, pt-BR;q=0.8, en;q=0.1") == "pt"
    assert i18n.negotiate(None, "en;q=0, pt;q=0.5") == "pt"
    assert i18n.negotiate(None, "fr") == "en"
    assert i18n.negotiate("xx", None) == "en"


def test_pages_render_in_the_negotiated_locale_and_set_html_lang():
    with TestClient(make_app()) as client:
        res = client.http.get("/", headers={"accept-language": "pt-BR,pt;q=0.9", "accept": "text/html"})
        assert 'lang="pt"' in res.text and "Olá, Ada! 2 itens English" in res.text
        res = client.http.get("/", headers={"accept": "text/html"})
        assert 'lang="en"' in res.text and "Hello, Ada! 2 items" in res.text
        client.http.cookies.set("rw_lang", "pt")
        assert "Olá, Ada!" in client.http.get("/", headers={"accept": "text/html"}).text


def test_from_directory_and_validation(tmp_path):
    (tmp_path / "en.json").write_text(json.dumps({"a": "A"}), encoding="utf-8")
    (tmp_path / "pt.json").write_text(json.dumps({"a": "Á"}), encoding="utf-8")
    assert I18n.from_directory(tmp_path, default="pt").translate("en", "a") == "A"
    assert I18n.from_directory(tmp_path, default="pt").default == "pt"
    with pytest.raises(ValueError):
        I18n({})
    with pytest.raises(ValueError):
        I18n({"en": {}}, default="de")


def test_set_locale_op_and_no_i18n_app():
    assert js.set_locale("pt").to_json() == ["set_locale", None, "pt"]
    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return Button(self.t("plain"), on_click=js.set_locale("en"))

    with TestClient(app) as client:
        assert "plain" in client.open("/").text
