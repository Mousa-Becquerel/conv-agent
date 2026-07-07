"""Per-user (or per-IP) rate limiting via FastAPI dependencies.

We started on slowapi but its function-wrapping decorator confuses FastAPI's
signature introspection — Body / Depends params get reclassified as query
params and every endpoint 422s. A dependency-based limiter avoids that
entirely and is about 30 lines.

Buckets are in-process sliding windows keyed by user_id (when a valid
access token is present) or client IP. For multi-replica prod we'd swap
the `_buckets` dict for Redis sorted-sets keyed the same way.

Note: deliberately no `from __future__ import annotations` — FastAPI needs to
resolve `Request` in our `__call__` signature at registration time.
"""

import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from auth.tokens import TokenError, decode_token


def _parse_limit(spec: str) -> tuple[int, int]:
    """Parse a `N/period` string. Period accepts second/minute/hour/day."""
    count_str, _, period_str = spec.partition("/")
    count = int(count_str.strip())
    period_str = period_str.strip().lower().rstrip("s")
    period = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}.get(period_str)
    if period is None:
        raise ValueError(f"unknown rate-limit period {spec!r}")
    return count, period


CHAT_RATE_LIMIT = os.getenv("CHAT_RATE_LIMIT", "30/hour")
LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "10/minute")
# Voice transcription is more expensive per request and easier to abuse
# (someone could record a long meeting and transcribe it). Lower default.
TRANSCRIBE_RATE_LIMIT = os.getenv("TRANSCRIBE_RATE_LIMIT", "10/hour")


def per_user_or_ip_key(request: Request) -> str:
    """Bucket key: authenticated user id if we can validate the bearer token,
    otherwise the client IP."""
    auth = request.headers.get("authorization", "")
    parts = auth.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        try:
            user_id = decode_token(parts[1], expected_type="access")
            return f"user:{user_id}"
        except TokenError:
            pass
    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


# Shared in-process buckets — process-local. For multi-replica deploy,
# back with Redis (`ZADD <bucket> <ts> <ts>` + `ZREMRANGEBYSCORE <bucket> 0 <ts-window>`).
_buckets: dict[str, deque[float]] = defaultdict(deque)


class RateLimit:
    """Sliding-window rate limiter usable as a FastAPI Depends.

    Two consecutive requests at the same time use the same bucket only if
    the key function returns the same value — i.e. per-user when the token
    is valid, per-IP otherwise.
    """

    def __init__(self, spec: str, name: str = ""):
        self.count, self.period = _parse_limit(spec)
        self.spec = spec
        self.name = name or spec

    def __call__(self, request: Request) -> None:
        key = f"{self.name}|{per_user_or_ip_key(request)}"
        now = time.monotonic()
        window = _buckets[key]
        cutoff = now - self.period
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self.count:
            retry_after = max(1, int(window[0] + self.period - now))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"rate limit exceeded ({self.spec})",
                headers={"Retry-After": str(retry_after)},
            )
        window.append(now)


# Instances used as Depends targets.
chat_rate_limit = RateLimit(CHAT_RATE_LIMIT, name="chat")
login_rate_limit = RateLimit(LOGIN_RATE_LIMIT, name="login")
transcribe_rate_limit = RateLimit(TRANSCRIBE_RATE_LIMIT, name="transcribe")
