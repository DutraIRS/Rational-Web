from pydantic import BaseModel


class LoginForm(BaseModel):
    """The admin sign-in form."""

    password: str
