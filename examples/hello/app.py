"""The smallest Rational Web app: one static, themed page (no JavaScript is shipped).

Run:  python examples/hello/app.py --dev    # hot reload, readable errors
      python examples/hello/app.py --prod   # production server
then open http://127.0.0.1:8000
"""

from rational import App, Card, Container, Heading, Page, Text

app = App(title="Hello")


@app.page("/")
class Hello(Page):
    def render(self):
        return Container(
            Card(
                Heading("Hello, Rational Web", level=1),
                Text("This page is plain server-rendered HTML with compiled, themed CSS.", muted=True),
            ),
            tag="main",
            max_width=640,
        )


if __name__ == "__main__":
    app.run()
