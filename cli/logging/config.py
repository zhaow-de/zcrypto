from __future__ import annotations

import logging
import sys
import warnings
from pathlib import Path

from cli.logging.formatters import JsonLineFormatter, PlainTextFormatter

_TARGET_LOGGERS = ("zcrypto", "qlib")


def configure(path: Path | None, level: str) -> None:
    """Set up project + qlib loggers. Idempotent across repeated calls."""
    numeric = logging.getLevelName(level)
    if not isinstance(numeric, int):
        raise ValueError(f"invalid log level: {level!r}")

    # See docs/open-topics/T0000-qlib-empty-slice-warnings.md
    warnings.filterwarnings(
        "ignore",
        message="Mean of empty slice",
        category=RuntimeWarning,
        module="qlib.utils.index_data",
    )

    handler: logging.Handler
    if path is None:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(PlainTextFormatter())
    else:
        handler = logging.FileHandler(path, mode="a", encoding="utf-8")
        handler.setFormatter(JsonLineFormatter())
    handler.setLevel(numeric)
    handler._zcrypto_owned = True  # type: ignore[attr-defined]

    for name in _TARGET_LOGGERS:
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            if getattr(h, "_zcrypto_owned", False):
                lg.removeHandler(h)
                try:
                    h.close()
                except OSError:
                    pass
        lg.addHandler(handler)
        lg.setLevel(numeric)
        lg.propagate = False

    # qlib caches loggers behind QlibLogger; clamp its internal manager too.
    import qlib.log  # local import keeps `zcrypto --version` from pulling qlib

    qlib.log.set_global_logger_level(numeric)
