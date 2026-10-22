from dataclasses import dataclass, field


@dataclass(frozen=True)
class SocialLink:
    label: str
    url: str


@dataclass(frozen=True)
class Job:
    role: str
    company: str
    period: str
    location: str
    highlights: tuple[str, ...]


@dataclass(frozen=True)
class Project:
    name: str
    summary: str
    tech: tuple[str, ...]
    url: str | None = None


@dataclass(frozen=True)
class Profile:
    name: str
    role: str
    location: str
    email: str
    summary: str
    links: tuple[SocialLink, ...]
    jobs: tuple[Job, ...]
    skills: dict[str, tuple[str, ...]]
    projects: tuple[Project, ...]
    education: tuple[str, ...] = field(default=())

    @property
    def technologies(self) -> list[str]:
        """Every technology used in a project, for the filter buttons."""
        return sorted({tech for project in self.projects for tech in project.tech})
