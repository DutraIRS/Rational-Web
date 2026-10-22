from rational import Button, Container, Heading, Page, Router, Row, js

from views.components import Counter, Greeter
from views.styles import PAGE

router = Router()


@router.page("/")
class Home(Page):
    title = "Counter · Rational Web"

    def render(self):
        return Container(
            Row(
                Heading("Counter", level=1),
                Button("Toggle theme", variant="ghost", on_click=js.toggle_theme()),  # runs in the browser
                justify="between",
            ),
            Row(
                Counter(key="one"),  # different keys: each counter keeps its own count
                Counter(key="ten", label="Tens", step=10),
                collapse="mobile",
                align="stretch",
            ),
            Greeter(),
            tag="main",
            max_width=720,
            style=PAGE,
        )
