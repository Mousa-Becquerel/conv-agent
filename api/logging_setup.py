"""structlog configuration.

Call `configure_logging()` once at startup. After that, anywhere in the app:

    from logging_setup import get_logger
    log = get_logger(__name__)
    log.info("chat_complete", user_id="...", latency_ms=1234)

Two output formats:
  - LOG_FORMAT=pretty (default) — human-readable, colorized when a TTY.
  - LOG_FORMAT=json — machine-parseable, ship to Datadog / Loki / CloudWatch.

Context binding: request_id, user_id, and conversation_id are stored in
ContextVars so they propagate through async tasks within a request. The
processor `_inject_context` pulls them into every log line automatically —
no need to repeat the same keys on every call.
"""

import logging
import os
import sys
from contextvars import ContextVar
from typing import Optional

import structlog


LOG_FORMAT = os.getenv("LOG_FORMAT", "pretty").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


# Context vars: set by middleware / dependencies, read by the processor below.
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar("user_id", default=None)
conversation_id_var: ContextVar[Optional[str]] = ContextVar("conversation_id", default=None)


def _inject_context(logger, method_name, event_dict):
    """Merge per-request context vars into every log event."""
    rid = request_id_var.get()
    if rid:
        event_dict.setdefault("request_id", rid)
    uid = user_id_var.get()
    if uid:
        event_dict.setdefault("user_id", uid)
    cid = conversation_id_var.get()
    if cid:
        event_dict.setdefault("conversation_id", cid)
    return event_dict


def configure_logging() -> None:
    """Configure structlog + tame noisy stdlib loggers. Idempotent."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    level_no = getattr(logging, LOG_LEVEL, logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _inject_context,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if LOG_FORMAT == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level_no),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Quiet libraries that would otherwise drown the chat logs we care about.
    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str = ""):
    """Return a bound logger. Pass `__name__` from the calling module."""
    return structlog.get_logger(name)
