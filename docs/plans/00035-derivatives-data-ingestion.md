# Derivatives-data ingestion (OI / long-short / basis) — Implementation Plan (iter-38)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** ingest the free Binance futures derivatives streams as new qlib fields, per spec
`docs/specs/00035-derivatives-data-ingestion-design.md`. **Data only** — signals + A/B are iter-39.
Mirror the existing `$funding` ingestion end-to-end. All data free (no credentialed source).

**Tech stack:** Python 3.12, the existing `cli/data/` pipeline, pytest, uv.

## Global Constraints

- Mirror the funding-ingestion pattern (`cli/data/binance.py` `funding_archive_parts`/`funding_url`/
  `fetch_funding_archive`; `cli/data/klines.py` decoder; `cli/data/config.py` `FIELDS`; `cli/data/pipeline.py`
  download/backfill/verify/delist/rename + the spot↔perp map; same-day `$close` alignment; NaN-before-launch).
- **OI + long-short are daily-granularity only** on the free archive. New fields same-day aligned with `$close`.
- **Probe the live archive layout first** (`data.binance.vision`) — do NOT assume the metrics/basis column names.
- TDD; ruff before each commit; no network in unit tests (synthetic zips). Heavy real fetches run in background.

## File Structure

- Modify: `cli/data/binance.py` (metrics + basis archive URL builders + fetch methods)
- Create/Modify: a metrics/basis decoder (sibling to `cli/data/klines.py`)
- Modify: `cli/data/config.py` (`FIELDS` += the new `$`-fields), `cli/data/pipeline.py` (thread the fields)
- Modify: `README.md` (data section), `docs/iterations-history.md` (closeout)
- Tests: `tests/test_data_*.py` (decoder + pipeline + verify-coverage)

---

### Task 0: Probe the archive layout (write findings to `.tmp/`)

- [ ] Probe `data.binance.vision` for the futures UM **`metrics/`** daily archive of a covered perp (e.g.
  `BTCUSDT`) and the **basis** source (markPriceKlines / premiumIndexKlines): confirm the URL path, zip
  layout, and exact column names. Record in `.tmp/derivatives-archive-layout.md` (a reversible note). This
  grounds Tasks 1-2; if a stream's layout differs materially from the spec, adapt the field set + log it.

### Task 1: `metrics/` ingestion (OI + long-short + taker ratio)

**Files:** `cli/data/binance.py` (+ `metrics_archive_parts`/`metrics_url`/`fetch_metrics_archive`); a decoder; tests.

- [ ] **Step 1 — failing decoder test** (synthetic metrics zip → normalized daily rows with `$oi`,
  `$oi_value`, `$ls_global`, `$ls_top`, `$taker_ratio`), mirroring the kline/funding decoder tests.
- [ ] **Step 2 — red.** **Step 3 — implement** the URL builder + fetch + decoder (mirror funding).
- [ ] **Step 4 — green** + ruff. **Step 5 — commit** `feat(data): ingest futures metrics (OI + long-short) archive`.

### Task 2: basis ingestion (`$basis`)

**Files:** `cli/data/binance.py` (basis archive builder + fetch); decoder; tests.

- [ ] **Step 1 — failing decoder test** (synthetic basis zip → daily `$basis` = `(mark − index)/index` or the
  archived premium index, per Task 0's finding).
- [ ] **Step 2 — red.** **Step 3 — implement.** **Step 4 — green** + ruff.
- [ ] **Step 5 — commit** `feat(data): ingest perp-spot basis archive`.

### Task 3: pipeline integration (lifecycle + fields)

**Files:** `cli/data/config.py`, `cli/data/pipeline.py`; tests.

- [ ] **Step 1 — failing test:** a pipeline fixture run surfaces the new `$`-fields in the compiled dataset,
  same-day aligned with `$close`, NaN before a perp's launch; `verify` reports their per-coin coverage; the
  spot↔perp map (incl. `PEPE→1000PEPEUSDT`, MATIC→POL) carries them; `delist`/`rename` handle them.
- [ ] **Step 2 — red.** **Step 3 — implement** (add to `FIELDS`; thread through download/backfill/verify/
  delist/rename, mirroring `$funding`). **Step 4 — green** + ruff.
- [ ] **Step 5 — commit** `feat(data): wire OI/long-short/basis through the dataset lifecycle`.

### Task 4: real fetch + verify (background, heavy)

- [ ] **Step 1 — run** `zcrypto data download`/`backfill` for the universe to fetch the new streams (background,
  redis n/a; heavy network) — or a bounded subset first to validate end-to-end.
- [ ] **Step 2 — `zcrypto data verify`** → record per-coin coverage of the new fields. Handle gaps/short
  histories like funding (NaN/partial). If a coin/stream 404s, log + continue (don't block).

### Task 5: closeout

- [ ] **README** data section: the new `$`-fields ride the normal data lifecycle (mirror the `$funding` note).
- [ ] **`docs/iterations-history.md`** iter-38 entry: data landed + coverage; **next = iter-39** derivatives
  signals (OI-divergence / basis extremes / funding dispersion / long-short contrarian) A/B vs `beta_null`.
- [ ] Open-topic or next-step note for iter-39.
- [ ] **Commit** `docs: iter-38 closeout — derivatives data ingested (OI/long-short/basis)`.

## Iterations-history note

Task 5 appends the iter-38 entry; the derivatives **signals** (iter-39) are the downstream EV test this data unlocks.
