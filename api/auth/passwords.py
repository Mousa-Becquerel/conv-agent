"""Argon2id password hashing.

argon2id is the OWASP-recommended algorithm — it's memory-hard, GPU-resistant,
and the parameter selection here uses argon2-cffi's defaults which target
~100ms on modern hardware. Parameters live with the hash (`$argon2id$v=19$m=...$`),
so we can tune cost later without breaking existing users — `verify_password`
keeps working, and `needs_rehash` flags hashes that should be rebuilt at
next login.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


# Single shared hasher — thread-safe.
_ph = PasswordHasher()


def hash_password(plain: str) -> str:
    """Return an argon2id-encoded hash for storage in `users.password_hash`."""
    return _ph.hash(plain)


def verify_password(plain: str, stored_hash: str) -> bool:
    """Constant-time check; returns False on mismatch or malformed hash."""
    try:
        return _ph.verify(stored_hash, plain)
    except VerifyMismatchError:
        return False
    except Exception:
        # Malformed hash, library version mismatch, etc. Treat as failed auth
        # rather than 500ing — same observable behaviour as a wrong password.
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when the hash was produced with weaker parameters than we now use.

    Call this after a successful verify; if True, re-hash the plaintext and
    persist the new value. Lets us tune cost parameters without forcing a
    password reset.
    """
    try:
        return _ph.check_needs_rehash(stored_hash)
    except Exception:
        return False
