"""Regressions for the cross-cutting security and concurrency fixes."""

import json

import pytest

from rational import App, Page, PersistentSessionStore
from rational.events import js as js_ns
from rational.rendering import UnsafeMarkupError, h, to_html
from rational.stores import MemorySessionDriver
from rational.testing import TestClient

# -- srcdoc / js.set_attr XSS ---------------------------------------------------------------


def test_srcdoc_attribute_is_rejected():
    with pytest.raises(UnsafeMarkupError):
        to_html(h("iframe", srcdoc="<script>alert(1)</script>"))


def test_js_set_attr_rejects_executable_markup():
    with pytest.raises(ValueError):
        js_ns.set_attr("srcdoc", "<img src=x onerror=alert(1)>")
    with pytest.raises(ValueError):
        js_ns.set_attr("onclick", "alert(1)")


def test_js_set_attr_rejects_unsafe_urls():
    for scheme in ("javascript:alert(1)", "vbscript:x", "data:text/html;base64,PHNjcmlwdD4="):
        with pytest.raises(ValueError):
            js_ns.set_attr("href", scheme)
        with pytest.raises(ValueError):
            js_ns.toggle_attr("href", scheme, "#ok")


def test_js_set_attr_allows_safe_values():
    js_ns.set_attr("href", "/home")
    js_ns.set_attr("aria-expanded", "true")
    js_ns.toggle_attr("aria-expanded")


# -- route registry --------------------------------------------------------------------------


def test_duplicate_page_path_is_rejected():
    app = App()

    @app.page("/")
    class A(Page):
        def render(self):
            return None

    with pytest.raises(TypeError, match="already registered"):

        @app.page("/")
        class B(Page):
            def render(self):
                return None


def test_same_page_class_at_two_paths():
    app = App()

    @app.page("/one")
    @app.page("/two")
    class Both(Page):
        def render(self):
            return None

    assert sorted(app.routes) == ["/one", "/two"]
    with pytest.raises(ValueError, match="multiple paths"):
        app.url_for(Both)
    assert app.url_for(Both, _path="/one") == "/one"
    assert app.url_for(Both, _path="/two") == "/two"
    with TestClient(app) as client:
        assert client.open("/one").status_code == 200
        assert client.open("/two").status_code == 200


# -- handler signatures ----------------------------------------------------------------------


def test_starargs_handler_is_rejected():
    from rational.binding import check_signature

    with pytest.raises(TypeError, match="must not take \\*args"):
        check_signature(lambda *args: None)


def test_two_required_arguments_is_rejected():
    from rational.binding import check_signature

    with pytest.raises(TypeError, match="at most one argument"):
        check_signature(lambda a, b: None)


# -- persistent store concurrency -------------------------------------------------------------


async def test_conflicting_writes_do_not_diverge():
    driver = MemorySessionDriver()
    a = PersistentSessionStore(driver)
    b = PersistentSessionStore(driver)

    sa = a.create()
    sa["x"] = "0"
    await a.save(sa)  # persist so worker B can load it
    sb = await b.load(sa.id)
    assert sb is not None

    sa["x"] = "A"
    sb["x"] = "B"
    await a.save(sa)
    await b.save(sb)  # must adopt A's version, not silently keep its own view

    raw = await driver.get("rational:session:" + sb.id)
    payload = json.loads(raw)
    assert payload["data"]["x"] == "B"  # both changed x: the last writer wins

    again = await a.load(sb.id)
    assert again is not None
    again["y"] = 1
    await a.save(again)  # worker A must not keep a stale same-version view

    raw2 = await driver.get("rational:session:" + sb.id)
    assert json.loads(raw2)["data"] == {"x": "B", "y": 1}


async def test_logout_cannot_be_resurrected_by_a_stale_worker():
    driver = MemorySessionDriver()
    a = PersistentSessionStore(driver)
    b = PersistentSessionStore(driver)

    sa = a.create()
    sa["rw.user"] = "alice"
    await a.save(sa)
    sid = sa.id
    sb = await b.load(sid)
    assert sb is not None

    # Worker A logs out (rotation deletes the old id; the save writes the new one).
    sa.logout()
    await a.rotate(sa)
    await a.save(sa)
    assert await driver.get("rational:session:" + sid) is None

    # Worker B, holding an in-flight change from before the logout, saves afterwards.
    sb["note"] = "late"
    await b.save(sb)
    assert await driver.get("rational:session:" + sid) is None  # still gone: no resurrection
    assert b.get(sid) is None


async def test_rotation_deletes_the_old_record_and_the_save_writes_the_new_one():
    driver = MemorySessionDriver()
    store = PersistentSessionStore(driver)
    session = store.create()
    session["rw.user"] = "ada"
    await store.save(session)
    old = session.id
    await store.rotate(session)
    assert await driver.get("rational:session:" + old) is None
    await store.save(session)
    raw = await driver.get("rational:session:" + session.id)
    assert raw is not None and json.loads(raw)["data"]["rw.user"] == "ada"
