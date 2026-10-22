"""What the account forms may submit. Validators raise friendly messages, shown under each field."""

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignUpForm(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)
    confirm: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        if not EMAIL.match(value.strip()):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("confirm")
    @classmethod
    def passwords_match(cls, value: str, info: Any) -> str:
        if value != info.data.get("password"):
            raise ValueError("Passwords do not match")
        return value


class SignInForm(BaseModel):
    email: str
    password: str


class ProfileForm(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    bio: str = Field(default="", max_length=280)


class PasswordForm(BaseModel):
    current: str
    new: str = Field(min_length=8, max_length=128)
