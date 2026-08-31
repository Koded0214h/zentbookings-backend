from __future__ import annotations

import json
import logging
import sys

from app.core.config import settings

_SENSITIVE = ("password", "token", "secret", "authorization", "code")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    if settings.LOG_FORMAT.lower() == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-5s %(name)s : %(message)s", "%H:%M:%S")
        )

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    # uvicorn's own access logger is redundant with our request middleware
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in ("uvicorn.error", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))


def redact_query(query: str) -> str:
    """Mask values of sensitive query params so they never reach logs/metrics."""
    if not query:
        return ""
    parts = []
    for pair in query.split("&"):
        key, sep, _ = pair.partition("=")
        parts.append(f"{key}=***" if sep and key.lower() in _SENSITIVE else pair)
    return "&".join(parts)
