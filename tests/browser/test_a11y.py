"""Automated accessibility checks on a page that uses most components.

These catch structural problems (names, labels, ids, ARIA references, focus visibility). They do not
replace a manual audit with a screen reader, and they do not measure colour contrast.
"""

import pytest

from rational import (
    App,
    Button,
    Checkbox,
    Heading,
    Image,
    Input,
    Main,
    Menu,
    MenuItem,
    Modal,
    Page,
    Select,
    Table,
    Tabs,
    Text,
    Toast,
    Toasts,
)
from tests.browser._support import collect_errors, serve

pytestmark = pytest.mark.browser

PIXEL = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="

AUDIT = """() => {
  const problems = [];
  const name = (el) => (el.getAttribute("aria-label") || el.textContent || el.getAttribute("title") || "").trim();
  if (!document.documentElement.lang) problems.push("html has no lang");
  if (!document.title.trim()) problems.push("page has no title");
  if (document.querySelectorAll("main").length !== 1) problems.push("expected exactly one <main>");
  for (const img of document.querySelectorAll("img")) {
    if (!img.hasAttribute("alt")) problems.push("img without alt: " + img.src);
  }
  for (const el of document.querySelectorAll("input:not([type=hidden]), select, textarea")) {
    const labelled = (el.labels && el.labels.length)
      || el.getAttribute("aria-label") || el.getAttribute("aria-labelledby");
    if (!labelled) problems.push("control without a label: " + (el.name || el.id || el.tagName));
  }
  for (const el of document.querySelectorAll("button, a[href], [role=tab], [role=menuitem]")) {
    if (!name(el)) problems.push("interactive element without a name: " + el.outerHTML.slice(0, 80));
  }
  const ids = new Map();
  for (const el of document.querySelectorAll("[id]")) ids.set(el.id, (ids.get(el.id) || 0) + 1);
  for (const [id, n] of ids) if (n > 1) problems.push("duplicate id: " + id);
  for (const attr of ["aria-controls", "aria-labelledby", "aria-describedby"]) {
    for (const el of document.querySelectorAll("[" + attr + "]")) {
      for (const ref of el.getAttribute(attr).split(/\\s+/)) {
        if (ref && !document.getElementById(ref)) problems.push(attr + " points at a missing id: " + ref);
      }
    }
  }
  for (const table of document.querySelectorAll("table")) {
    if (!table.querySelector("th")) problems.push("table without header cells");
  }
  return problems;
}"""


def make_app():
    app = App(title="Accessible")

    @app.page("/")
    class Home(Page):
        title = "Everything"

        def render(self):
            return Main(
                Heading("Components"),
                Image(PIXEL, alt="Logo"),
                Image(PIXEL, alt=""),
                Input("Email", type="email", help="We never share it"),
                Input("Name", error="Required"),
                Select("Plan", ["Free", "Pro"]),
                Checkbox("Subscribe"),
                Table(["Name", "Role"], [["Ada", "Admin"]], caption="People"),
                Button("Open", on_click=None),
                Modal(Text("Body"), id="dlg", title="Confirm"),
                Tabs([("Alpha", Text("a")), ("Beta", Text("b"))], id="tabs"),
                Menu("Actions", MenuItem("Rename"), id="m"),
                Toasts(Toast("Saved", tone="success")),
            )

    return app


def test_page_passes_structural_checks(browser):
    server, thread, url = serve(make_app())
    try:
        page = browser.new_page()
        errors = collect_errors(page)
        page.goto(url)
        assert page.evaluate(AUDIT) == []
        assert errors == []
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_keyboard_focus_is_visible(browser):
    server, thread, url = serve(make_app())
    try:
        page = browser.new_page()
        page.goto(url)
        seen = 0
        for _ in range(8):
            page.keyboard.press("Tab")
            visible = page.evaluate(
                """() => {
                  const el = document.activeElement;
                  if (!el || el === document.body) return null;
                  const s = getComputedStyle(el);
                  return (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== "none";
                }"""
            )
            if visible is None:
                continue
            seen += 1
            assert visible, "the focused element has no visible focus indicator"
        assert seen >= 4
    finally:
        server.should_exit = True
        thread.join(timeout=5)
