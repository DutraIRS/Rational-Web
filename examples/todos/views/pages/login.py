from rational import Button, Card, Container, Form, Heading, Input, Page, Router, Text

from models import SignIn
from views.styles import LOGIN_PAGE

router = Router()


@router.page("/login")
class Login(Page):
    title = "Sign in · Todos"

    def sign_in(self, form: SignIn):
        self.context.session.login(form.name.strip())  # also rotates the session id
        self.navigate("/")

    def render(self):
        return Container(
            Card(
                Heading("Sign in", level=1),
                Text("Demo sign-in: pick any name. Each name sees only its own todos.", muted=True),
                Form(
                    Input("Your name", name="name", required=True, autocomplete="username"),
                    Button("Continue", type="submit", full_width=True),
                    on_submit=self.sign_in,
                ),
            ),
            tag="main",
            max_width=420,
            style=LOGIN_PAGE,
        )
