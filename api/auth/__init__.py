"""Authentication: argon2 password hashing, JWT issue + verify, FastAPI
dependencies for resolving the current user."""

from .deps import current_user, current_user_required, optional_user
from .passwords import hash_password, verify_password
from .tokens import create_access_token, create_refresh_token, decode_token

__all__ = [
    "current_user",
    "current_user_required",
    "optional_user",
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
]
