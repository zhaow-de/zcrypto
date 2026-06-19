# Binance perp funding-rate data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Acquire Binance USDT-perp funding-rate history for the 19 universe coins and store it as a queryable qlib field `$funding` (daily-sum carry), woven into every `zcrypto data` subcommand (`download`/`backfill`/`verify`/`delist`/`rename`) + a one-time idempotent retrofit script. Data-only; advances `T0010`.

**Architecture:** A pure funding layer (`cli/data/funding.py`: parse → daily-sum, + the spot↔perp mapping) feeds a `Source.fetch_funding_archive`; the pipelines write `features/<instrument>/funding.day.bin` via the existing `qlib_writer.write_bin`, aligned to the kline-defined daily calendar. Every data subcommand treats `$funding` like an OHLCV field; the futures-vs-spot remote source is invisible to the user.

**Tech Stack:** Python 3.12, uv, pandas, numpy, urllib3, pytest, ruff (line length 132). Data source: `data.binance.vision` (no qlib/redis in the data layer).

## Global Constraints

- **Funding is a transparent first-class field:** all of `download`/`backfill`/`verify`/`delist`/`rename` handle `$funding` exactly as they handle OHLCV; the different remote dir (futures `fundingRate` vs spot `klines`) is internal.
- **Additive / behavior-preserving:** the existing kline acquisition is unchanged; `$funding` is added alongside. A dataset built before this iteration stays valid (no `$funding` until retrofit).
- **Leak-safe alignment:** `$funding[D]` (day-D settlements) is same-day-aligned with `$close[D]`; missing/short → absent bin → NaN on query.
- **The retrofit script is idempotent** (a re-run leaves the dataset byte-identical), lives under `scripts/` with its own `scripts/README.md` (NOT the root README), and is tested.
- ruff clean; data tests use `tests/data_fixtures.py::FakeSource` (no network); each commit gets a subagent `Reviewed-by:` before push.

## File structure

```
cli/data/
├── funding.py     # NEW: parse_funding (pure) + daily_funding (8h->daily sum) + perp_symbol (spot<->perp mapping, time-dependent)
├── binance.py     # MODIFY: Source.fetch_funding_archive + funding_archive_parts/funding_url builders (futures fundingRate)
├── pipeline.py    # MODIFY: download_/backfill_ fetch+write funding.day.bin; delist_ removes it; rename_ carries/merges it + gap-NaN
├── qlib_writer.py # (reuse) write_bin/read_bin — no change
├── verify.py      # MODIFY: verify_dataset funding-coverage check (present/aligned; report coverage)
└── command.py     # (reuse/MODIFY only if a flag is needed) — no new subcommand
scripts/
├── backfill_funding.py   # NEW: one-time idempotent retrofit of $funding onto existing ./data
└── README.md             # NEW: flags backfill_funding.py one-time-use only
tests/
├── test_funding.py            # NEW: parse + daily-sum + perp_symbol mapping (pure)
├── data_fixtures.py           # MODIFY: FakeSource.fetch_funding_archive (synthetic funding)
├── test_data_pipeline.py      # EXTEND: download/backfill write funding.day.bin; delist removes; rename merges + gap-NaN
├── test_data_verify.py (or test_data_snapshots) # EXTEND: verify funding-coverage
└── test_backfill_funding.py   # NEW: retrofit correctness + idempotency (2nd run byte-identical)
```

Tasks 1–2 build the pure + fetch layer; 3 the write-on-download/backfill; 4 delist/rename; 5 verify; 6 the retrofit script; 7 closeout (real-data populate + docs).

---

## Task 1: Pure funding layer — parse, daily-sum, spot↔perp mapping

**Files:** Create `cli/data/funding.py`; Test `tests/test_funding.py`.

**Interfaces (produces):**
- `perp_symbol(instrument: str, on: dt.date) -> str | None` — the perp symbol to source funding from for `instrument` on `on`; `None` during a rename gap.
- `parse_funding(raw: bytes) -> list[tuple[dt.datetime, float]]` — `(settlement_time_utc, funding_rate)` rows from one funding archive.
- `daily_funding(rows: list[tuple[dt.datetime, float]]) -> dict[dt.date, float]` — sum the rate by UTC date.

- [ ] **Step 0 (RECON — do first):** Confirm the Binance funding source format: the `data.binance.vision` futures `fundingRate` archive path (likely `futures/um/monthly/fundingRate/<PERP>/<PERP>-fundingRate-<YYYY-MM>.zip`), the CSV columns (e.g. `calc_time`/`funding_time`, `funding_rate`/`last_funding_rate`), the settlement cadence (8-hourly), and the time unit (ms epoch?). If Vision archives don't exist/are awkward, note the `/fapi/v1/fundingRate` API shape as the fallback. Record findings in the report; the parser below conforms to what you find. (Use a real sample if reachable; else design to the documented schema + flag.)

- [ ] **Step 1: Failing tests** `tests/test_funding.py`:
```python
import datetime as dt
from cli.data.funding import perp_symbol, daily_funding, parse_funding

def test_perp_symbol_identity():
    assert perp_symbol("BTCUSDT", dt.date(2023, 1, 1)) == "BTCUSDT"

def test_perp_symbol_pepe_1000x():
    assert perp_symbol("PEPEUSDT", dt.date(2024, 1, 1)) == "1000PEPEUSDT"

def test_perp_symbol_pol_timesplit():
    assert perp_symbol("POLUSDT", dt.date(2024, 9, 10)) == "MATICUSDT"
    assert perp_symbol("POLUSDT", dt.date(2024, 9, 13)) == "POLUSDT"
    assert perp_symbol("POLUSDT", dt.date(2024, 9, 11)) is None  # rename gap
    assert perp_symbol("POLUSDT", dt.date(2024, 9, 12)) is None

def test_daily_funding_sums_settlements():
    d = dt.date(2024, 1, 1)
    rows = [(dt.datetime(2024,1,1,0), 0.0001), (dt.datetime(2024,1,1,8), 0.0002),
            (dt.datetime(2024,1,1,16), 0.0003), (dt.datetime(2024,1,2,0), 0.0005)]
    out = daily_funding(rows)
    assert abs(out[d] - 0.0006) < 1e-12
    assert abs(out[dt.date(2024,1,2)] - 0.0005) < 1e-12
```
Plus a `parse_funding` test on a synthetic archive matching the Step-0 recon'd schema.

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** `funding.py`: `perp_symbol` via an explicit mapping table (identity default; `PEPEUSDT→1000PEPEUSDT`; `POLUSDT` time-split per the recon'd MATIC→POL dates with the 09-11/12 gap → None); RECON the exact perp tickers for all 19 and encode them. `parse_funding` per the recon'd schema; `daily_funding` sums by UTC date. Pure (no qlib/network).
- [ ] **Step 4: Run — expect PASS + ruff.**
- [ ] **Step 5: Commit** — `feat(data): add pure funding layer (parse, daily-sum, spot↔perp mapping)` (+ `Co-Authored-By: Claude Opus 4.8` trailer).

---

## Task 2: `Source.fetch_funding_archive` + URL builders + FakeSource

**Files:** Modify `cli/data/binance.py`; Modify `tests/data_fixtures.py`; Test `tests/test_funding.py` (URL builder).

**Interfaces:** Produces `binance.funding_archive_parts(perp, year, month) -> (rel_dir, name)`, `funding_url(perp, year, month) -> str`, and `Source.fetch_funding_archive(perp, year, month) -> bytes` (real `BinanceSource` impl + `FakeSource`).

- [ ] **Step 1: Failing test** for `funding_archive_parts`/`funding_url` (assert the recon'd path, e.g. `futures/um/monthly/fundingRate/BTCUSDT/...`); and that `FakeSource.fetch_funding_archive` returns synthetic bytes parseable by `parse_funding`.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** the URL builders (mirroring `kline_archive_parts`/`kline_zip_url`, but the futures base/path) + add `fetch_funding_archive` to the `Source` Protocol and `BinanceSource` (HTTP GET via the existing `_pool` pattern; handle 404 = no archive that month). Add `fetch_funding_archive` to `FakeSource` (synthetic monthly funding for requested perps). RECON: the exact futures base URL + monthly path.
- [ ] **Step 4: Run — expect PASS + ruff.**
- [ ] **Step 5: Commit** — `feat(data): add Binance funding archive fetch + URL builders`.

---

## Task 3: Write `$funding` on download + backfill

**Files:** Modify `cli/data/pipeline.py`; Test `tests/test_data_pipeline.py`.

**Design:** In `download_pipeline` (and `backfill_pipeline`), after the kline bins are written for each pair, fetch that pair's funding: for each `perp_symbol(instrument, date)` over the instrument's date range, fetch the needed monthly funding archives, `parse_funding` → `daily_funding`, align to the instrument's calendar range, and `write_bin(features/<instrument>/funding.day.bin, values, start_index)` with the SAME `start_index`/calendar alignment as the kline bins. Dates with no funding (pre-perp-launch, rename gap, archive 404) → absent/NaN (don't write a value; qlib returns NaN). Reuse the mirror-cache pattern for funding archives.

- [ ] **Step 1: Failing test** (FakeSource): `download_pipeline` over a tiny fixture writes `features/<inst>/funding.day.bin` for each pair; `read_bin` returns the expected daily-sum values aligned to the calendar; a pair whose FakeSource funding starts late has NaN/absent early funding. Mirror the existing pipeline tests' structure.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** the funding fetch+write in `download_pipeline` + `backfill_pipeline` (additive; klines unchanged). RECON: the monthly-archive fetch cadence vs the per-date kline fetch — fetch each needed month once per pair. Handle the POL source-split via `perp_symbol(instrument, date)`.
- [ ] **Step 4: Run — expect PASS + ruff.**
- [ ] **Step 5: Commit** — `feat(data): write $funding on download/backfill`.

---

## Task 4: `delist` + `rename` funding handling

**Files:** Modify `cli/data/pipeline.py` (`delist_pipeline`, `rename_pipeline`); Test `tests/test_data_pipeline.py`.

- [ ] **Step 1: Failing tests** (FakeSource): `delist_pipeline` removes the instrument's `funding.day.bin` together with its OHLCV bins; `rename_pipeline` (e.g. OLD→NEW) carries/merges the funding bin across old→new and leaves the rename gap as NaN, mirroring the OHLCV handling. Assert the funding bin's presence/absence + the gap.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** funding handling in `delist_pipeline` (delete `funding.day.bin` with the rest) + `rename_pipeline` (merge/carry funding across the rename, gap-NaN), consistent with how each already treats OHLCV.
- [ ] **Step 4: Run — expect PASS + ruff.**
- [ ] **Step 5: Commit** — `feat(data): handle $funding in delist and rename`.

---

## Task 5: `verify` funding coverage

**Files:** Modify `cli/data/verify.py`; Test `tests/test_data_verify.py` (or the existing verify test file).

- [ ] **Step 1: Failing test:** `verify_dataset` on a dataset with funding reports a funding-coverage `check` per traded instrument (present, decodable, aligned to the calendar) and does NOT hard-fail on a short/absent perp history (it reports it). A structurally-corrupt funding bin IS flagged.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** the funding-coverage check in `verify_dataset` (decode `funding.day.bin`, check `start_index`/length consistency vs the calendar; append a human-readable coverage `check`; flag only structural problems).
- [ ] **Step 4: Run — expect PASS + ruff.**
- [ ] **Step 5: Commit** — `feat(data): verify $funding coverage`.

---

## Task 6: One-time idempotent retrofit script + `scripts/README.md`

**Files:** Create `scripts/backfill_funding.py`, `scripts/README.md`; Test `tests/test_backfill_funding.py`.

**Design:** A standalone script (runnable as `uv run python scripts/backfill_funding.py [--data-dir ...]`) that, for each instrument in an existing dataset lacking `$funding`, fetches+writes its `funding.day.bin` (reusing the Task 1–3 funding layer). **Idempotent:** if `funding.day.bin` already exists for an instrument (and covers its range), skip it — a full re-run writes nothing new and leaves the dataset byte-identical. Structure the core as an importable function so the test can drive it with `FakeSource`.

- [ ] **Step 1: Failing tests** `tests/test_backfill_funding.py` (FakeSource, on a tiny klines-only fixture): (a) first run writes `funding.day.bin` for each instrument with the expected values; (b) **idempotency** — capture each `funding.day.bin`'s bytes after run 1, run again, assert the bytes are unchanged (byte-identical); (c) it does not touch OHLCV bins.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** `scripts/backfill_funding.py` (idempotent: skip instruments whose funding bin already covers the range) + `scripts/README.md` (one paragraph: this dir holds one-time-use ops scripts; `backfill_funding.py` retrofits `$funding` onto a pre-funding dataset, safe to re-run, not part of the routine `zcrypto data` flow).
- [ ] **Step 4: Run — expect PASS + ruff.**
- [ ] **Step 5: Commit** — `feat(data): one-time idempotent $funding retrofit script + scripts/README`.

---

## Task 7: Closeout — populate the real dataset + docs

**Files:** Modify `docs/open-topics/T0010-non-ohlcv-features.md` + `docs/open-topics/README.md`; `README.md`; `docs/iterations-history.md`.

- [ ] **Step 1: Populate the real `./data`.** Run `uv run python scripts/backfill_funding.py` (or a `download`/`backfill` cycle) against the real `./data` to fetch live Binance funding for the 19 and write `$funding`. Then `uv run zcrypto data verify` and confirm the funding-coverage report (the "data ready" evidence — note each coin's funding range, incl. the POL MATIC→POL split). Re-run the retrofit once to confirm idempotency on real data (no changes).
- [ ] **Step 2: Flip `T0010` → `partial`.** Front-matter `status: open → partial`; add `## Done so far` (the funding stream landed: `$funding` field, all-subcommand integration, retrofit script; iter-15 / spec `00014`); trim `## Suggested next steps` to the remainder (the funding *feature*/recipe/edge-test; on-chain; order-book). Move its bullet `## Open → ## Partially done` in `docs/open-topics/README.md`.
- [ ] **Step 3: README `## Usage`.** Note the `zcrypto data` subcommands now cover funding (`$funding`). Do NOT mention the retrofit script in the root README (it's in `scripts/README.md`). (mdformat owns the README TOC.)
- [ ] **Step 4: iterations-history** iter-15 entry: the pure funding layer + mapping (incl. PEPE 1000× and the POL time-split), the funding archive fetch, `$funding` written/extended/verified/delisted/renamed across all `zcrypto data` subcommands, the idempotent retrofit script, the real-data coverage result; `T0010` partial; next = the funding feature + edge-test.
- [ ] **Step 5: Commit** — `docs(data): iter-15 closeout — funding coverage, T0010 partial, iterations-history`.

---

## Self-review

- **Spec coverage:** `$funding` qlib field (Tasks 1–3) ✓; daily-sum, same-day-aligned (Task 3) ✓; all subcommands seamless — download/backfill (3), delist/rename (4), verify (5) ✓; spot↔perp mapping incl. PEPE 1000× + POL time-split (Task 1) ✓; Vision source + API fallback (Tasks 1–2 RECON) ✓; idempotent retrofit + `scripts/README` + tested (Task 6) ✓; data-only, T0010 partial, real-data populate (Task 7) ✓; no new subcommand ✓.
- **Type consistency:** `perp_symbol(instrument, on)->str|None`, `parse_funding(bytes)->list[(datetime,float)]`, `daily_funding(rows)->dict[date,float]`, `Source.fetch_funding_archive(perp,year,month)->bytes`, `write_bin(funding.day.bin, values, start_index)` — consistent across tasks.
- **Risk flags:** the Binance funding **source format** is the lead RECON (Task 1 Step 0 / Task 2) — the parser/fetcher conform to what's found; if Vision lacks the archives, the `/fapi/v1/fundingRate` API is the fallback (same `Source` seam, same downstream). The pure layer (Task 1) is isolated + unit-tested; the pipeline integration (3–5) uses `FakeSource` so it needs no network.
