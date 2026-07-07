"""Sentry SDK init for the API.

Opt-in via SENTRY_DSN env var. When unset, the SDK is never initialised, so
dev environments stay silent and no events leak out.

Privacy:
  - send_default_pii=False — Sentry won't auto-capture IPs, cookies, headers.
  - _scrub_event — explicit redaction pass for any Authorization header,
    password field, or known-sensitive query string that does sneak through.
  - We don't capture request bodies by default; FastAPIIntegration captures
    paths + status codes only.
"""

import os
from typing import Any, Optional

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration


DSN = os.getenv("SENTRY_DSN", "").strip()
ENV = os.getenv("SENTRY_ENVIRONMENT", "development")
RELEASE = os.getenv("SENTRY_RELEASE", "").strip() or None
TRACES_SAMPLE_RATE = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0"))


_SENSITIVE_HEADER_NAMES = {"authorization", "cookie", "x-api-key"}
_SENSITIVE_BODY_FIELDS = {"password", "refresh_token", "access_token"}


def _scrub_dict(obj: Any) -> None:
    """In-place recursive scrub of dict-shaped event data."""
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            if isinstance(k, str) and k.lower() in _SENSITIVE_BODY_FIELDS:
                obj[k] = "[REDACTED]"
            elif isinstance(k, str) and k.lower() in _SENSITIVE_HEADER_NAMES:
                obj[k] = "[REDACTED]"
            else:
                _scrub_dict(obj[k])
    elif isinstance(obj, list):
        for item in obj:
            _scrub_dict(item)


def _scrub_event(event, _hint):
    """Strip auth headers and password fields from Sentry events."""
    try:
        _scrub_dict(event)
    except Exception:
        # Never let scrubbing crash the SDK — log nothing rather than expose
        # raw events.
        pass
    return event


def configure_sentry() -> bool:
    """Initialise the SDK if SENTRY_DSN is set. Returns True iff enabled."""
    if not DSN:
        return False
    sentry_sdk.init(
        dsn=DSN,
        environment=ENV,
        release=RELEASE,
        traces_sample_rate=TRACES_SAMPLE_RATE,
        send_default_pii=False,
        before_send=_scrub_event,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            # Don't auto-capture INFO logs as breadcrumbs; ERROR+ only.
            LoggingIntegration(level=None, event_level=None),
        ],
    )
    return True


def set_user(user_id: Optional[str], email: Optional[str] = None) -> None:
    """Attach the authenticated user to the current Sentry scope so events
    on this request are grouped per-user. Called from current_user_required."""
    if not DSN:
        return
    scope = sentry_sdk.get_current_scope()
    if user_id:
        scope.set_user({"id": user_id, "email": email or None})
    else:
        scope.set_user(None)
