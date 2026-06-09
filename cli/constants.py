from __future__ import annotations


class CliConstants:
    """Centralized low-change operational config for the `zcrypto` CLI.

    Convention: high-change-odds config (per-invocation knobs, user-facing
    behavior) goes on a Typer flag. Low-change-odds operational tuning lives
    here as a class attribute and is changed by editing this file — small
    surface, easy to discover, no env-var or hidden-config sprawl.
    """

    FETCH_CONCURRENCY = 5
    """Max parallel HTTP fetches in ``zcrypto data download``. Gentle by
    default to avoid hammering ``data.binance.vision``."""
