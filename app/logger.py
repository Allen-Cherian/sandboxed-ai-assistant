"""Structured audit logging.

Emits JSON-line events to both stdout (captured by the container runtime) and a
file inside the dedicated logs directory. Designed as an *audit trail* — "who
uploaded what, what was asked, what sources were used" — not just debug output.

Secret values are redacted: any field whose key matches a secret-name pattern is
replaced with ``"***REDACTED***"``. See ``docs/security_model.md`` §6.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

# Redact any field whose key ends with one of these secret-name patterns.
# (`API_KEY` is already covered by the `_KEY` suffix.)
_SECRET_KEY_RE = re.compile(r"(_KEY|_TOKEN|_SECRET|PASSWORD)$", re.IGNORECASE)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***REDACTED***" if _SECRET_KEY_RE.search(k) else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


class JsonLineFormatter(logging.Formatter):
    """Render each record as a single JSON object on one line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        # Structured fields attached via logger.info(msg, extra={"fields": {...}}).
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload["data"] = _redact(fields)
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_configured = False


def setup_logging(logs_dir: Path, level: str = "INFO") -> None:
    """Configure the root audit logger once."""

    global _configured
    if _configured:
        return

    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("assistant")
    logger.setLevel(level)
    logger.propagate = False

    fmt = JsonLineFormatter()

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    try:
        file_handler = logging.FileHandler(logs_dir / "audit.log.jsonl", encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError:
        # If the logs dir is not writable, we still have stdout. Never crash the
        # app over logging setup.
        logger.warning("could_not_open_log_file", extra={"fields": {"dir": str(logs_dir)}})

    _configured = True


def get_logger() -> logging.Logger:
    return logging.getLogger("assistant")


def audit(event: str, **fields: Any) -> None:
    """Convenience helper: emit a structured audit event."""

    get_logger().info(event, extra={"fields": fields})
