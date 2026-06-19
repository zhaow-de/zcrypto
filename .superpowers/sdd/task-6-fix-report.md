# Task 6 Fix Report — iter-15: three targeted post-hoc fixes

## Fixes applied

### Fix 1 — `scripts/backfill_funding.py` `main()` config API crash

**Bug**: `main()` referenced `cfg.data.data_dir` and `cfg.data.backup_dir`, but `AppConfig` has no
`.data` attribute — `data_dir`, `backup_dir`, and `fetch` are top-level fields. Also, `BinanceSource()`
was constructed without `cfg.fetch`.

**Fix**: Moved `load_config`, `resolve_data_dir`, `resolve_backup_dir` to module-level imports (enabling
monkeypatching). Replaced the broken attribute accesses with the correct calls:

```python
cfg = load_config()
data_dir = resolve_data_dir(args.data_dir, cfg)
backup_dir = resolve_backup_dir(None, cfg)
paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
source = BinanceSource(fetch=cfg.fetch)
```

### Fix 2 — `cli/data/pipeline.py` `_funding_for_pair` perp-attribution bleed

**Bug**: The inner loop `for day, rate in daily_funding(parse_funding(raw)).items()` only checked
`from_date <= day <= to_date`, but did not verify that the day actually maps to the archive's perp via
`perp_symbol(instrument, day)`. This meant a POLUSDT archive that contained a settlement on 2024-09-01
(a MATIC-attributed date) would inject that settlement into the output — wrong perp data for that day.

**Fix**: Added the perp-attribution guard:

```python
if from_date <= day <= to_date and perp_symbol(instrument, day) == perp:
    out[day] = rate
```

## RED evidence (before fixes)

Running the three new tests before applying any fix:

```
FAILED tests/test_backfill_funding.py::test_main_resolves_paths_and_calls_core
  AttributeError: 'module' object at scripts.backfill_funding has no attribute 'load_config'
  (load_config was a local import inside main() — not patchable at module level)

FAILED tests/test_funding.py::test_funding_for_pair_pol_split
  AssertionError: 09-01 (MATIC date) must be absent — POLUSDT archive data must not bleed
  into MATIC dates; got 0.999
  assert datetime.date(2024, 9, 1) not in {datetime.date(2024, 9, 8): 0.001,
                                            datetime.date(2024, 9, 1): 0.999,
                                            datetime.date(2024, 9, 13): 0.009}

PASSED tests/test_funding.py::test_funding_for_pair_pepe_1000x
  (basic routing already worked; test validates it continues to work)
```

## New tests added

**`tests/test_backfill_funding.py`** — `test_main_resolves_paths_and_calls_core`:
Monkeypatches `load_config` (now importable at module level) and `retrofit_funding`, sets
`sys.argv` to `["backfill_funding"]` to isolate from pytest args, then calls `main()` and
asserts the resolved paths match the patched config.

**`tests/test_funding.py`** — `test_funding_for_pair_pol_split`:
MATICUSDT Sept-2024 archive has a settlement on 2024-09-08 (rate 0.001).
POLUSDT Sept-2024 archive has a settlement on 2024-09-01 (rate 0.999 — a MATIC-attributed date,
must be excluded) and 2024-09-13 (rate 0.009 — a POL-attributed date, must be included).
Asserts: 09-01 absent, 09-08 present with MATIC rate, 09-13 present with POL rate,
09-11/09-12 (rename gap) absent.

**`tests/test_funding.py`** — `test_funding_for_pair_pepe_1000x`:
Registers archive under `1000PEPEUSDT`, calls `_funding_for_pair("PEPEUSDT", ...)`, asserts
the settlement is present in the result (validates the 1000× name routing).

## Final state

- 102 tests pass (full target suite: test_data_pipeline, test_data_rename, test_data_delist,
  test_data_verify, test_backfill_funding, test_funding).
- ruff check and ruff format: all clear.

## Files changed

- `scripts/backfill_funding.py` — Fix 1: module-level imports + correct config API in `main()`
- `cli/data/pipeline.py` — Fix 2: perp-attribution guard in `_funding_for_pair`
- `tests/test_backfill_funding.py` — new `test_main_resolves_paths_and_calls_core` test
- `tests/test_funding.py` — new `test_funding_for_pair_pol_split` + `test_funding_for_pair_pepe_1000x` tests
