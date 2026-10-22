from rational import Button, Card, Component, Form, Heading, Input, Row, State, Text, Textarea

from models import PasswordForm, ProfileForm, UserOut
from services import AccountService


class ProfileSettings(Component):
    saved: bool = False

    async def save(self, form: ProfileForm):
        await self.use(AccountService).update_profile(form.name, form.bio)
        self.navigate("/settings?saved=profile")  # a fresh page also shows the new name in the header

    def render(self):
        user: UserOut = self.context.user
        return Card(
            Heading("Profile", level=2),
            Form(
                Input("Name", name="name", value=user.name, required=True),
                Textarea("Bio", name="bio", value=user.bio, rows=3, help="Up to 280 characters."),
                Row(
                    Button("Save profile", type="submit"),
                    Text("Profile saved.", role="status", color="success", size="sm") if self.saved else None,
                ),
                on_submit=self.save,
            ),
        )


class PasswordSettings(Component):
    changed = State(0)

    async def change(self, form: PasswordForm):
        # A wrong current password raises FieldError: the message appears under that field.
        await self.use(AccountService).change_password(form.current, form.new)
        self.changed += 1  # also gives the form a new key, which clears the fields

    def render(self):
        return Card(
            Heading("Password", level=2),
            Form(
                Input(
                    "Current password", name="current", type="password", required=True, autocomplete="current-password"
                ),
                Input(
                    "New password",
                    name="new",
                    type="password",
                    required=True,
                    autocomplete="new-password",
                    help="At least 8 characters.",
                ),
                Row(
                    Button("Change password", type="submit"),
                    Text("Password changed.", role="status", color="success", size="sm") if self.changed else None,
                ),
                on_submit=self.change,
                key=f"password-{self.changed}",
            ),
        )
