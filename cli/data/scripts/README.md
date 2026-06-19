This directory holds one-time-use operational scripts that are not part of the routine `zcrypto data` flow.
`backfill_funding.py` retrofits `$funding` (funding.day.bin) onto an existing dataset that was built before
the funding layer was added; it is safe to re-run (idempotent: instruments whose funding.day.bin already
covers the full date range are skipped, leaving the dataset byte-identical).
Run it with `uv run python cli/data/scripts/backfill_funding.py [--data-dir <path>]`.
