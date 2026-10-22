from rational import Badge, Card, Component, Grid, Row, Style, Text

from .section import Section
from content import PROFILE
from views.styles import FLAT_CARD

GROUP_TITLE = Style(text_transform="uppercase", letter_spacing="0.06em")


class Skills(Component):
    def render(self):
        groups = [
            Card(
                Text(group, weight=700, size="sm", style=GROUP_TITLE),
                Row(*[Badge(skill, tone="primary") for skill in skills], gap="xs", wrap=True),
                style=FLAT_CARD,
            )
            for group, skills in PROFILE.skills.items()
        ]
        return Section("skills", "Skills", Grid(*groups, min_column_width=220))
