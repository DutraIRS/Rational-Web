"""Sign-up, sign-in, the dashboard and settings."""

from rational import (
    Avatar,
    Badge,
    Button,
    ButtonLink,
    Card,
    Column,
    Form,
    Grid,
    Heading,
    Input,
    Link,
    Page,
    Router,
    Row,
    State,
    Text,
)

from models import SignInForm, SignUpForm, UserOut
from services import AccountService, safe_next
from views.components import PasswordSettings, ProfileSettings, Shell
from views.styles import NARROW_CARD

router = Router()


@router.page("/", auth="required")
class Dashboard(Page):
    title = "Dashboard · User platform"

    def render(self):
        user: UserOut = self.context.user
        return Shell(
            Card(
                Row(
                    Avatar(user.name, size=64),
                    Column(
                        Heading(f"Welcome, {user.name}", level=1),
                        Row(
                            Badge(user.role, tone="primary" if user.is_admin else "neutral"),
                            Text(f"Member since {user.created_at:%B %Y}", muted=True, size="sm"),
                            gap="sm",
                        ),
                        gap="xs",
                    ),
                    gap="lg",
                ),
                Text(user.bio or "You haven't written a bio yet.", muted=not user.bio),
            ),
            Grid(
                Card(
                    Heading("Profile", level=3),
                    Text("Update your name, bio and password.", muted=True),
                    ButtonLink("Open settings", href="/settings", variant="secondary"),
                ),
                Card(
                    Heading("API", level=3),
                    Text("Every service is also a typed JSON API.", muted=True),
                    ButtonLink("Explore in Swagger UI", href="/api/docs", variant="secondary"),
                ),
                min_column_width=260,
            ),
        )


@router.page("/signup")
class SignUp(Page):
    title = "Create account · User platform"

    async def create(self, form: SignUpForm):
        user = await self.use(AccountService).register(form.name, form.email, form.password)
        self.context.session.login(user.id)  # stores the id and rotates the session id
        self.navigate("/")

    def render(self):
        return Shell(
            Card(
                Heading("Create your account", level=1),
                Text("The first account becomes an administrator.", muted=True),
                Form(
                    Input("Name", name="name", required=True, autocomplete="name"),
                    Input("Email", name="email", type="email", required=True, autocomplete="email"),
                    Input(
                        "Password",
                        name="password",
                        type="password",
                        required=True,
                        autocomplete="new-password",
                        help="At least 8 characters.",
                    ),
                    Input(
                        "Confirm password", name="confirm", type="password", required=True, autocomplete="new-password"
                    ),
                    Button("Create account", type="submit", full_width=True),
                    on_submit=self.create,
                ),
                Text("Already have an account? ", Link("Sign in", href="/login"), size="sm"),
                style=NARROW_CARD,
            )
        )


@router.page("/login")
class Login(Page):
    title = "Sign in · User platform"
    next_url = State("/")

    def mount(self):
        # Query parameters belong to the page request, so read them in mount(), not in handlers.
        self.next_url = safe_next(self.request.query_params.get("next"))

    async def sign_in(self, form: SignInForm):
        user = await self.use(AccountService).authenticate(form.email, form.password)
        self.context.session.login(user.id)
        self.navigate(self.next_url)

    def render(self):
        return Shell(
            Card(
                Heading("Sign in", level=1),
                Form(
                    Input("Email", name="email", type="email", required=True, autocomplete="email"),
                    Input("Password", name="password", type="password", required=True, autocomplete="current-password"),
                    Button("Sign in", type="submit", full_width=True),
                    on_submit=self.sign_in,
                ),
                Text("New here? ", Link("Create an account", href="/signup"), size="sm"),
                style=NARROW_CARD,
            )
        )


@router.page("/settings", auth="required")
class Settings(Page):
    title = "Settings · User platform"
    saved = State(False)

    def mount(self):
        self.saved = self.request.query_params.get("saved") == "profile"

    def render(self):
        return Shell(Heading("Settings", level=1), ProfileSettings(saved=self.saved), PasswordSettings())
