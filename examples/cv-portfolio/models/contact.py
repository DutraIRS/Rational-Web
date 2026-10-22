import re
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ContactForm(BaseModel):
    """What the contact form may submit, with friendly messages."""

    name: str = Field(min_length=1, max_length=80)
    email: str = Field(max_length=254)
    message: str = Field(min_length=10, max_length=4000)
    website: str = ""  # the honeypot: hidden from people, filled in by bots

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        if not EMAIL.match(value.strip()):
            raise ValueError("Enter a valid email address so I can reply")
        return value.strip()

    @field_validator("message")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError("Tell me a little more (at least 10 characters)")
        return value.strip()


@dataclass(frozen=True)
class Message:
    name: str
    email: str
    message: str
    received_at: datetime
