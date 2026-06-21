# Binance perp funding-rate data — Design

**Iteration:** iter-15
**Advances open-topic:** `T0010` (non-OHLCV features) — the funding stream; flipped to `partial` at closeout.
**First of the "data foundation" program** (funding → delisted-klines/PIT → aggTrades → [on-chain if a free source covers the universe]); chosen first because funding is the only stream with edge-revealing potential.
**Depends on:** spec `00003`/`00004`/`00005` (the `cli/data` kline pipeline, qlib writer, verify, delist/rename that this extends).

## Context — what

The `cli/data` layer is entirely spot-OHLCV: `download`/`backfill`/`verify`/`delist`/`rename` fetch daily kline zips from `data.binance.vision`, and `qlib_writer` dumps per-field `<field>.day.bin` files (open/high/low/close/volume) per instrument. The experiment's feature handlers (Alpha158, the iter-13 cross-asset processor) therefore only ever see price/volume.

This iteration acquires **Binance USDT-perpetual funding-rate history** for the 19 universe coins and stores it as a first-class qlib field **`$funding`** (queryable via `D.features`, on the existing daily calendar), so a later iteration can build a funding-carry feature the way the cross-asset processor reads `$close`. Funding is woven into the **existing** data lifecycle so every `zcrypto data` subcommand (`download`/`backfill`/`verify`/`delist`/`rename`) handles it seamlessly — no new subcommand, and the user never sees that it comes from a different remote dir — plus a one-time retrofit script for the existing dataset.

## Why this matters

Per iter-14, recipe/feature tuning on price/volume is exhausted — nothing survives the seed-noise test and all variants lose. Funding rate is a **genuinely new signal** Alpha158 lacks: persistent funding encodes crowded positioning (high positive funding = crowded longs → a documented mean-reversion / carry signal), and research §14 notes the 8-hour perpetual-funding timestamps propagate into spot. It is the cheapest *new-information* bet available (tiny data, free source) and the one data stream that could plausibly move the project off its no-edge result.

## Goal

Make `$funding` a queryable qlib field for the 19 coins, integrated into `download`/`backfill`/`verify` + a one-time retrofit script — **data only**; the funding feature/recipe/edge-test is the next iteration.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Scope = data-only:** acquire + daily-aggregate + store `$funding` as a per-instrument qlib field. No funding feature, recipe, or edge-test this iteration. | "Make the data ready, then decide the topic" — the feature/edge is the next, separately-decided iteration (it'll use the iter-14 multi-seed harness to test the edge honestly). |
| 2 | **`$funding[D]` = the daily SUM of the day's 8-hourly funding settlements** (00:00/08:00/16:00 UTC), aligned to the SAME daily-bar convention as `$close[D]`. | The natural daily carry; one number per day. Storing the daily aggregate (vs raw 8-hourly) keeps it simple; the feature iteration can refine if it needs intraday funding. Same-day alignment with `$close` means feature engineering uses the identical `Ref` lag discipline — no special lookahead handling. |
| 3 | **Source = `data.binance.vision` futures `fundingRate` archives** (free, no-auth, reuses the download/mirror/parse pattern), with the `/fapi/v1/fundingRate` futures API as fallback. | Consistency with the existing kline acquisition. RECON: confirm the exact archive path + CSV schema (funding archives are **monthly** per symbol, a different cadence than the per-date kline zips) and the API fallback. |
| 4 | **No new command — every `zcrypto data` subcommand handles `$funding` seamlessly.** `download` fetches it (alongside klines), `backfill` extends it, `verify` checks its coverage, `delist` removes the instrument's `funding.day.bin` together with its OHLCV, and `rename` carries/merges the funding bin across old→new + fills the rename gap with NaN — exactly as each already does for price/volume. The different remote source (futures `fundingRate` dir vs spot `klines` dir) is an internal detail the user never sees. A **one-time retrofit script** (`scripts/`) populates `$funding` onto the existing klines-only `./data` without a full re-download. | Funding is a transparent first-class field of every instrument, not a bolt-on; consistency across ALL subcommands is the requirement. The retrofit script is the one-off to close the gap on the current dataset. |
| 5 | **Spot↔perp symbol mapping** is an explicit, possibly time-dependent table: identity for most (`BTCUSDT`→`BTCUSDT` perp), with unit-scaled exceptions — notably **PEPE: spot `PEPEUSDT` → perp `1000PEPEUSDT`** (the funding *rate* is unitless, so it applies directly regardless of the 1000× contract) — and a **time-split for the POL instrument: the perp renamed in lockstep with spot, so funding comes from the `MATICUSDT` perp for dates ≤ 2024-09-10 and the `POLUSDT` perp for dates ≥ 2024-09-13, with 2024-09-11/12 → NaN** (the same 2-day gap as the spot rename). | Most perps share the spot ticker, but meme/low-price coins use `1000x` perps and renamed coins switch source mid-history. RECON: confirm the exact perp ticker for all 19; the MATIC→POL dates are given. |
| 6 | **Missing/short funding → `$funding = NaN`** (perps launched after spot for some coins; archive gaps), handled downstream by the feature layer's `Fillna` — same as any warmup. `verify` reports funding coverage, not hard-fails on a short perp history. | Funding history is naturally shorter than spot for some coins; NaN is the honest representation; the feature iteration decides fill semantics. |
| 7 | **The one-time retrofit script is idempotent, locally documented, and tested.** `scripts/backfill_funding.py` **mutates nothing after the first run** — a re-run detects `$funding` already present and no-ops (no re-fetch, no overwrite, no corruption). It is **NOT referenced from the root README**; a brief `scripts/README.md` flags it as one-time-use only. Despite being one-time, it is **tested like a command** (retrofit correctness + idempotency: a second run leaves the dataset byte-identical). | A one-time script that might be run twice must be safe to re-run; local docs keep the root README clean; tests prevent a destructive retrofit. |

## Component file tree

```
cli/data/
├── binance.py     # MODIFY: Source.fetch_funding(...) + funding archive/URL builders (Vision futures fundingRate); API fallback
├── funding.py     # NEW: parse a funding archive/response → daily-summed (date -> funding) aligned series; the spot<->perp mapping table
├── pipeline.py    # MODIFY: download_/backfill_ fetch+write funding; delist_ removes funding.day.bin with OHLCV; rename_ carries/merges funding + fills rename-gap NaN
├── qlib_writer.py # (reuse) write_bin writes funding.day.bin per instrument — no change to the writer itself
├── verify.py      # MODIFY: verify_dataset gains a funding-coverage check (funding.day.bin present + aligned; report coverage)
└── command.py     # MODIFY: download/backfill/verify gain funding awareness (NO new subcommand)
scripts/
├── backfill_funding.py   # NEW: one-time retrofit — populate $funding onto existing ./data (no kline re-download); POL source-split (MATICUSDT perp <=2024-09-10, POLUSDT perp >=2024-09-13, 09-11/12 NaN); IDEMPOTENT (mutates nothing after the first run)
└── README.md             # NEW: scripts/ readme — flags backfill_funding.py as one-time-use only (NOT referenced from the root README)
tests/
├── test_funding.py            # NEW: pure parse + daily-sum aggregation + spot<->perp mapping
├── test_backfill_funding.py   # NEW: retrofit correctness + IDEMPOTENCY (a second run leaves the dataset byte-identical)
├── test_data_*.py             # EXTEND: download/backfill write funding.day.bin; verify checks coverage; delist removes it; rename merges it (reuse the fake-source fixtures)
└── (verify/snapshot tests)    # EXTEND: funding field present in the dataset structure
```

## Acquisition & storage

- **Fetch** (`binance.py` + `funding.py`): for each of the 19 coins' perp symbols, fetch funding history from the Vision futures `fundingRate` archives (monthly CSVs; mirror-cached like klines), parse → 8-hourly rows → **daily sum** per date.
- **Align & write**: align the daily funding series to the dataset's daily calendar (the kline-defined 24/7 calendar); write `features/<instrument>/funding.day.bin` via `qlib_writer.write_bin` with the matching `start_index`. Dates before the perp launched or with archive gaps are absent (→ `$funding` NaN on query).
- **Lifecycle (all subcommands, seamless)**: `download` fetches + writes funding alongside klines on a fresh build; `backfill` extends it to the right edge with the klines; `delist` removes the instrument's `funding.day.bin` together with its OHLCV; `rename` carries/merges the funding bin across the old→new symbol and fills the rename gap with NaN, mirroring the OHLCV handling (the perp renamed in sync with the spot — e.g. MATIC→POL, whose perp also renamed); `verify` reports funding coverage; the one-time `scripts/backfill_funding.py` retrofits the existing dataset — **idempotent: a re-run mutates nothing** (detects `$funding` present, no-ops). The user never sees that funding comes from a different remote dir.

## Leakage & alignment

`$funding[D]` (day-D settlements) is same-day-aligned with `$close[D]` (day-D close) — both known at end of day D. Feature engineering (next iteration) applies qlib's standard `Ref` lag exactly as it does for prices, so no funding-specific lookahead handling is needed. (The data iteration's only obligation is correct same-day alignment to the existing calendar.)

## Verify

`verify_dataset` gains a funding-coverage check: `funding.day.bin` present per traded instrument, decodable, and aligned to the calendar (start_index within range, length consistent). It **reports** coverage (e.g. "BTCUSDT funding 2019-09..2026-06; PEPEUSDT funding 2023-05..2026-06") and flags only structural corruption — a short perp history is expected, not a failure.

## Scope & deferred

- **In:** funding fetch + daily-sum aggregation + `$funding` qlib field for the 19; download/backfill/verify integration; the one-time retrofit script; tests.
- **Out (next iteration):** the funding *feature* (carry / funding-momentum / z-score), a recipe, the multi-seed edge-test.
- **Out (later in the data program):** delisted-klines/PIT (`T0005`), aggTrades (`T0004`), on-chain (`T0010`, gated on a free source covering the 19); order-book (deferred).
- **Untouched:** the experiment/recipe/strategy layers; the spot kline acquisition (funding is additive).

## Closeout tasks (authored when the work is real)

- Flip `T0010` to `partial` (funding stream landed; non-OHLCV remainder = on-chain/order-book + the funding *feature* still open).
- README `## Usage`: note that the `zcrypto data` subcommands now cover funding (`$funding`). Do NOT reference the retrofit script in the root README — add a brief `scripts/README.md` flagging `backfill_funding.py` as one-time-use only instead.
- A verify run confirming `$funding` coverage across the 19 (the "data ready" evidence); iter-15 iterations-history entry.
