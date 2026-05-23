"""Local-only logging helpers for the Esri assessment CLI.

The module uses the stdlib :mod:`logging` package and exposes a single
``configure`` entry point. No handler in this module sends data over the
network — telemetry is explicit and off by default per project policy.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_LOGGER_NAME = "honua_esri_assess"


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter for structured local logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_KEYS:
                continue
            payload[key] = value
        return json.dumps(payload, default=str, sort_keys=True)


_RESERVED_LOG_RECORD_KEYS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def configure(level: int | str = logging.WARNING, *, json_format: bool = False) -> logging.Logger:
    """Configure the package logger with a single stderr handler.

    Idempotent: repeat calls replace the handler so test fixtures can swap
    formats without piling up handlers.
    """

    logger = logging.getLogger(_LOGGER_NAME)
    for existing in list(logger.handlers):
        logger.removeHandler(existing)

    handler = logging.StreamHandler(stream=sys.stderr)
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def get_logger(suffix: str | None = None) -> logging.Logger:
    """Return a child logger under the package root."""

    if suffix is None:
        return logging.getLogger(_LOGGER_NAME)
    return logging.getLogger(f"{_LOGGER_NAME}.{suffix}")


__all__ = ["JsonFormatter", "configure", "get_logger"]
