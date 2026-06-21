This directory holds one-time-use operational scripts that are not part of the routine `zcrypto data` flow.

`backfill_funding.py` retrofits `$funding` (funding.day.bin) onto an existing dataset that was built before
the funding layer was added; it is safe to re-run (idempotent: instruments whose funding.day.bin already
covers the full date range are skipped, leaving the dataset byte-identical).
Run it with `uv run python cli/data/scripts/backfill_funding.py [--data-dir <path>]`.

`acquire_old_luna.py` is a one-time, idempotent script that acquires Terra's old-LUNA klines as `LUNCUSDT`
in the compiled dataset. It works around the fact that Binance reused the `LUNAUSDT` symbol: old LUNA's
archives end at the 2022-05-13 Terra crash, then the same symbol carries Luna 2.0 from 2022-05-31. The
script fetches old-LUNA klines bounded at 2022-05-13 (the cap) so Luna 2.0 data is never touched, inserts
them as `LUNAUSDT`, then calls `rename_pipeline` to rename to `LUNCUSDT` with a NaN suspension gap for the
interval between the cap and LUNC's first archive day (2022-09-09). The LUNC tail from 2022-09-09 onward is
picked up by the next routine `zcrypto data backfill` run. Re-running after success is a no-op (already-
acquired short-circuit); re-running after a partial run (Phase 1 done, Phase 2 not) resumes at Phase 2.
Run it with `uv run python cli/data/scripts/acquire_old_luna.py [--data-dir <path>] [--dry-run]`.
