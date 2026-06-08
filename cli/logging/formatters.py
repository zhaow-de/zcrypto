from __future__ import annotations

import json
import logging
import time

_OMIT_EXTRA_KEYS = set(logging.LogRecord("x", logging.INFO, "x", 0, "", (), None).__dict__.keys()) | {"message", "asctime"}


class JsonLineFormatter(logging.Formatter):
    """Emit one JSON object per record (file mode)."""

    def format(self, record: logging.LogRecord) -> str:
        ms = int(record.msecs) % 1000
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{ms:03d}Z"
        payload: dict = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "file": record.filename,
            "line": record.lineno,
            "message": record.getMessage(),
        }
        # Underscore keys are reserved for stdlib/internal bookkeeping and never surface as user extras.
        extra = {k: v for k, v in record.__dict__.items() if k not in _OMIT_EXTRA_KEYS and not k.startswith("_")}
        if extra:
            payload["extra"] = extra
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class PlainTextFormatter(logging.Formatter):
    """qlib-style line, PID/thread stripped (console mode)."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)s %(name)s [%(filename)s:%(lineno)d] - %(message)s",
        )
