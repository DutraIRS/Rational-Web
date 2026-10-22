"""Password hashing (standard library scrypt) and safe redirects."""

import hashlib
import hmac
import secrets

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    """``scrypt$<salt>$<digest>``, with a random 16-byte salt per password."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
    return hmac.compare_digest(candidate.hex(), digest)  # constant time


def safe_next(value: str | None) -> str:
    """Only same-site paths: never redirect to another origin (open-redirect protection)."""
    return value if value and value.startswith("/") and not value.startswith("//") else "/"
