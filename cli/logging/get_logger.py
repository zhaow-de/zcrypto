from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    """Return the project-namespaced logger for `name`."""
    return logging.getLogger(f"zcrypto.{name}")
