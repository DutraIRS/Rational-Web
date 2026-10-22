from rational import Container, Footer, Page, Router, Text

from content import PROFILE
from views.components import Contact, Experience, Hero, Projects, SiteHeader, Skills
from views.styles import FOOTER, WIDTH

router = Router()


@router.page("/")
class Home(Page):
    title = f"{PROFILE.name} · {PROFILE.role}"
    description = PROFILE.summary

    def render(self):
        return [
            SiteHeader(),
            Container(Hero(), Experience(), Skills(), Projects(), Contact(), tag="main", max_width=WIDTH),
            Footer(
                Container(Text(f"© {PROFILE.name}. Built with Rational Web.", muted=True, size="sm"), max_width=WIDTH),
                style=FOOTER,
            ),
        ]
