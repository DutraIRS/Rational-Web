from rational import Button, Card, Component, Form, Heading, Input, Link, State, Style, Text, Textarea, h

from .section import Section
from content import PROFILE
from models import ContactForm
from services import ContactService
from views.styles import OFF_SCREEN


class Contact(Component):
    """Validated with a Pydantic model; errors appear under each field. A hidden "website"
    field catches bots: people never see it, so anything typed there is spam."""

    sent_to = State("")

    def send(self, form: ContactForm):
        self.use(ContactService).send(form.name, form.email, form.message, form.website)
        self.sent_to = form.name

    def render(self):
        if self.sent_to:
            body = Card(
                Heading(f"Thanks, {self.sent_to}!", level=3),
                Text("Your message is on its way. I usually reply within two days."),
                role="status",
                style=Style(border_color="success"),
            )
        else:
            body = Form(
                Input("Name", name="name", required=True, autocomplete="name"),
                Input("Email", name="email", type="email", required=True, autocomplete="email"),
                Textarea("Message", name="message", required=True, rows=5),
                # The honeypot: off-screen and hidden from assistive technology, so only bots fill it in.
                h(
                    "div",
                    Input("Website", name="website", tabindex="-1", autocomplete="off"),
                    aria_hidden="true",
                    style=OFF_SCREEN,
                ),
                Button("Send message", type="submit"),
                on_submit=self.send,
                style=Style(max_width=560),
            )
        return Section(
            "contact",
            "Contact",
            Text(
                "Have a project in mind? Write to me here or at ",
                Link(PROFILE.email, href=f"mailto:{PROFILE.email}"),
                ".",
            ),
            body,
        )
