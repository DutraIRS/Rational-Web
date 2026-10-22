from pydantic import BaseModel, Field


class SignIn(BaseModel):
    """The demo sign-in form: just a name."""

    name: str = Field(min_length=1, max_length=40, pattern=r"^[\w .-]+$")
