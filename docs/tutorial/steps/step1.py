"""Tutorial step 1: an app with one page."""

from rational import App, Container, Heading, Page, Text

app = App(title="Guestbook")


@app.page("/")
class Home(Page):
    title = "Guestbook"

    def render(self):
        return Container(
            Heading("Guestbook", level=1),
            Text("Leave a message for the next visitor."),
            max_width=640,
        )


if __name__ == "__main__":
    app.run()
