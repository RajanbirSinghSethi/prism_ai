"""Terminal-friendly logging for CLI and API."""

from __future__ import annotations

import logging
import sys


def configure_logging(level: str | int = "INFO") -> None:
    """Configure root logging once. Safe to call multiple times (replaces handlers)."""
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    datefmt = "%H:%M:%S"

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("httpx", "httpcore", "chromadb", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)
