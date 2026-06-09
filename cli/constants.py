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

    RENAME_SYNTH_WARN_DAYS = 7
    """Synthetic-gap-fill days threshold for rename Variant 1. Gaps larger than this
    emit a louder warning; smaller gaps emit a standard info-level warning."""

    BACKFILL_RIGHT_EDGE_GRACE_DAYS = 7
    """How many days a TRADING pair's right edge can be absent from the archive
    before backfill treats it as a likely delist/rename rather than archive
    publishing lag. Within this window: silent skip with info log. Beyond:
    PipelineError pointing at `data delist`/`data rename`."""

    HTTP_TIMEOUT_HEAD_SECS = 5
    """Socket timeout for HEAD / small-body (~kB) requests against data.binance.vision
    and api.binance.com. urllib defaults to unbounded — a stalled TLS handshake or
    network blip would hang forever without this. HEAD against S3-style archives is
    typically sub-second; 5s is a generous upper bound that fails fast on stalled
    connections (the retry loop then re-attempts)."""

    HTTP_TIMEOUT_GET_SECS = 60
    """Socket timeout for daily-zip GETs (~MB). Larger budget for the body transfer."""

    HTTP_RETRY_ATTEMPTS = 3
    """Total attempts per HTTP call before giving up. Retries on transient failures
    only (timeouts, connection resets, 5xx); 4xx propagates immediately."""
