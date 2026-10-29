"""Client components shared by the compiler tests and the browser tests (one app, many features)."""

import asyncio
from collections.abc import Callable

from rational import (
    App,
    Button,
    Checkbox,
    Column,
    Component,
    Input,
    Page,
    RemoteError,
    Row,
    State,
    Text,
    computed,
    watch,
)
from rational.backend import Service, remote
from rational.client import ClientComponent


class Todos(Service):
    @remote()
    def add(self, title: str) -> dict:
        if not title.strip():
            raise RemoteError("Write something first")
        return {"title": title.strip().title()}

    @remote(method="GET")
    def letters(self, word: str) -> int:
        return sum(ch.isalpha() for ch in word)


class Item(ClientComponent):
    title: str
    on_remove: Callable[[str], None] | None = None
    done = State(False)

    def toggle(self, checked: bool):
        self.done = checked

    def remove(self):
        self.on_remove(self.title)

    def render(self):
        return Row(
            Checkbox(self.title, name="done", checked=self.done, on_change=self.toggle),
            Button("Remove", on_click=self.remove, variant="ghost", aria_label=f"Remove {self.title}"),
        )


class TodoList(ClientComponent):
    items = State(factory=list)
    draft = State("")
    status = State("")

    def write(self, value: str):
        self.draft = value

    async def add(self):
        try:
            item = await self.remote(Todos.add, title=self.draft)
        except RemoteError as e:
            self.status = f"Error: {e.message}"
            return
        self.items = [*self.items, item["title"]]
        self.draft = ""
        self.status = "Counting..."
        await asyncio.sleep(0.05)
        letters = await self.remote(Todos.letters, word=item["title"])
        self.status = f"Added {item['title']} ({letters} letters)"

    def remove(self, title: str):
        self.items = [t for t in self.items if t != title]

    def render(self):
        return Column(
            Input("New todo", value=self.draft, on_input=self.write),
            Button("Add", on_click=self.add),
            *[Item(title=t, on_remove=self.remove, key=t) for t in self.items],
            Text(self.status or "Nothing yet"),
            self.children,
        )


class Clicks(Component):
    """A server component, passed into a client component as its child."""

    clicks = State(0)

    def click(self):
        self.clicks += 1

    def render(self):
        return Button(f"Server clicks: {self.clicks}", on_click=self.click)


class Counter(ClientComponent):
    label: str = "Count"
    count = State(0)

    def inc(self):
        self.count += 1

    def render(self):
        return Row(Text(f"{self.label}: {self.count}"), Button("+", on_click=self.inc, aria_label=f"{self.label} plus"))


class Echo(ClientComponent):
    text = State("")

    def say(self, value: str):
        self.text = value

    def render(self):
        return Column(Input("Say", value=self.text, on_input=self.say), Text(f"You said: {self.text.upper()}"))


class Shell(Component):
    title = State("First")

    def rename(self):
        self.title = "Second"

    def render(self):
        return Column(Button("Rename", on_click=self.rename), Counter(label=self.title), Echo())


class Semantics(ClientComponent):
    """Python semantics, evaluated by the server (first render) and by the compiled JavaScript (hydration)."""

    start: int = 7
    n = State(7)
    m = State(-7)
    f = State(2.675)
    xs = State(factory=lambda: [3, 1, 2])
    words = State("  Hello, wide   World  ")
    data = State(factory=lambda: {"b": 2, "a": 1})
    empty = State(factory=list)
    text = State("élan, naïve café")

    def mount(self):
        self.n = self.start

    def render(self):
        n, m, f, xs, words, data, empty, text = (
            self.n,
            self.m,
            self.f,
            self.xs,
            self.words,
            self.data,
            self.empty,
            self.text,
        )
        results = [
            n // 2,
            m // 2,
            n % 3,
            m % 3,
            n / 3,
            n**2,
            -n,
            abs(m),
            round(2.5 + n - n),
            round(3.5 + n - n),
            round(m + 4.5),
            round(f, 2),
            round(1234 + n - n, -2),
            str(True),
            str(None),
            str(xs),
            str(data),
            repr("it's"),
            repr(words.strip()),
            f"{f:.2f}",
            f"{n * 1000:,}",
            f"{n:>5}|",
            f"{n:^7}|",
            f"{f:08.3f}",
            f"{n:+d}",
            f"{f / 10:.1%}",
            f"{n * 123456:e}",
            f"{f:g}",
            f"{n * 37:x}",
            f"{words.strip():*^30}",
            f"{f:.2}",
            words.split(),
            words.split(",", 1),
            words.strip().lower(),
            words.title(),
            words.replace("l", "L", 2),
            "-".join(["a", "b", "c"]),
            words.find("wide"),
            words.count("l"),
            "ab".center(7, "."),
            str(n).zfill(4),
            words.strip().startswith(("Hello", "Bye")),
            text.upper(),
            len(text),
            text[1:4],
            text[::-2],
            sorted(xs),
            sorted(xs, reverse=True),
            sorted(["b", "A", "c"], key=lambda s: s.lower()),
            min(xs),
            max(xs, key=lambda x: -x),
            sum(xs),
            xs[-1],
            xs[::-1],
            list(reversed(xs)),
            [x * 2 for x in xs if x > 1],
            {k: v * 2 for k, v in data.items()},
            list(data.keys()),
            data.get("z", "none"),
            "a" in data,
            2 in xs,
            bool(empty),
            bool(xs),
            not empty,
            xs == [3, 1, 2],
            data == {"a": 1, "b": 2},
            empty or "fallback",
            xs and "yes",
            1 < n < 10,
            n is None,
            empty is not None,
            isinstance(n, int),
            isinstance(f, (int, float)),
            any(x > 2 for x in xs),
            all(x > 0 for x in xs),
            [list(pair) for pair in zip(xs, "abc")],  # noqa: B905 - compiled code: zip() takes no keywords
            int(" 42 "),
            float("2.5"),
            int(f),
            list(range(n, 0, -3)),
            "x" * 3,
            [0] * 2 + xs,
            xs.index(1),
            text.split(", "),
            words.strip().rsplit(" ", 1),
            str(-0.5),
        ]
        return Column(*[Text(repr(r), key=i) for i, r in enumerate(results)])


class Signup(ClientComponent):
    """Two-way binding, a computed value and a watcher, all in the browser."""

    name = State("")
    age = State(0)
    changes = State(factory=list)

    @computed
    def greeting(self):
        return f"Hi {self.name.title() or 'there'} ({self.age})"

    @watch("age")
    def aged(self, new, old):
        self.changes = [*self.changes, f"{old}->{new}"]

    def render(self):
        return Column(
            Input("Your name", bind=self.bind("name")),
            Input("Your age", type="number", bind=self.bind("age")),
            Text(self.greeting),
            Text(f"Changes: {', '.join(self.changes)}"),
        )


def make_app():
    app = App()
    app.service(Todos)

    @app.page("/signup")
    class SignupPage(Page):
        def render(self):
            return Signup()

    @app.page("/todos")
    class TodosPage(Page):
        def render(self):
            return TodoList(Clicks())

    @app.page("/")
    class Home(Page):
        def render(self):
            return Shell()

    @app.page("/cached-todos")
    class CachedTodos(Page):
        cache_control = "public, max-age=60"  # a CDN may keep it: it holds no visitor's token

        def render(self):
            return TodoList()

    @app.page("/semantics")
    class SemanticsPage(Page):
        def render(self):
            return Semantics(start=int(self.request.query_params.get("n", "7")))

    return app


ISLAND_ERRORS = (
    "window.__rw_errors = []; document.addEventListener('rw:error', (e) => window.__rw_errors.push(e.detail));"
)
TEXTS = "Array.from(document.querySelectorAll('rw-island p'), (p) => p.textContent)"
SERVER_TEXTS = """async (url) => {
    const html = await (await fetch(url)).text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    return Array.from(doc.querySelectorAll("rw-island p"), (p) => p.textContent);
}"""


def assert_same(python, javascript):
    mismatches = [(i, p, j) for i, (p, j) in enumerate(zip(python, javascript, strict=True)) if p != j]
    assert not mismatches, "\n".join(f"#{i}: python {p!r} != javascript {j!r}" for i, p, j in mismatches)
