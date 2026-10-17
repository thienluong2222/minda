"""Password hashing and revocable opaque sessions."""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

HASHER = PasswordHasher()
COOKIE = "meeting_session"
CSRF_COOKIE = "meeting_csrf"


def hash_password(password: str) -> str:
    return HASHER.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return HASHER.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def token() -> str:
    return secrets.token_urlsafe(32)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
