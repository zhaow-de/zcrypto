# aggTrades sample — execution-realism data — Design

**Iteration:** iter-17
**Advances open-topic:** `T0004` (realistic execution: slippage + maker-fill) → **`partial`** at closeout — this lands the **data + ingestion path**; the calibration (size-scaled slippage curve + maker-fill probability) and the backtest application are deferred to a dedicated future iteration.
**Third of the "data foundation" program** (funding [iter-15] → delisted-pair klines [iter-16] → **aggTrades** [this] → on-chain).
**Depends on:** the `cli/data` pipeline + mirror (specs `00003`/`00004`); reuses the kline fetch/mirror pattern.

## Context — what

The cost model is **fees-only**: `FEE_PRESETS` (open/close-cost fractions) → qlib's exchange via `exchange_kwargs(recipe)` (`scaffold.py`), with frictionless fills at the deal price — no slippage, no maker-fill modeling. `T0004` wants size-scaled slippage + maker-fill probability, which must be *calibrated* from trade-level data the daily dataset lacks. Binance publishes `data.binance.vision/spot/daily/aggTrades/<SYMBOL>/…` (tick-level: price, qty, timestamp, `isBuyerMaker`).

**aggTrades is a calibration input, not a panel.** Unlike `$funding`/OHLCV (per-(date,instrument) panels the backtest queries every run), aggTrades is huge tick-level data used *once* to estimate execution-cost parameters; no feature handler consumes it (Alpha158/360 are daily-OHLCV-only, confirmed). Its only use here is the `T0004` calibration. **Measured size:** BTCUSDT aggTrades ≈ **57 MB/day** (vs a 239-byte daily kline — ~238,000×); the full ~30-pair history would be **~1 TB** — so we acquire a **bounded sample**, not the full set.

This iteration is **data only**: build a first-class, reusable aggTrades **fetcher** in `zcrypto data`, and acquire a **bounded, liquidity-spanning sample** into the raw-archive store. No parsing-into-trades, no calibration, no backtest wiring.

## Why this matters

Research §6/§8/§13: slippage and unfilled maker orders are where frictionless backtests diverge from live P&L; thin books (Tier-3, PEPE) slip materially. Acquiring a representative aggTrades sample is the prerequisite for the `T0004` calibration. Building the fetcher as a **permanent** ingestion path (not a throw-away one-off) means the same path serves both the execution calibration *and* any future microstructure-feature work — without committing the ~1 TB full history to a not-yet-prioritized feature bet (features remain out of focus; the current research focus is model-level).

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Scope = DATA ONLY:** build the aggTrades fetcher + acquire a bounded sample to the raw-archive store. **No** trade parsing, **no** slippage/maker-fill calibration, **no** backtest/`exchange_kwargs` wiring. `T0004` → `partial`. | Matches the program's data-first cadence (funding/delisted preceded their uses). The calibration + application is a separate, dedicated iteration on top of this sample. |
| 2 | **First-class reusable fetcher**, mirroring the kline pattern: `aggtrades_archive_parts` / `fetch_aggtrades_archive` / `fetch_aggtrades_checksum` in `binance.py`. Not a throw-away one-off. | The same ingestion path serves the calibration now and any future microstructure-feature work later (`fetch more` is a re-invocation), so the bounded-sample choice never forces a rewrite. |
| 3 | **Storage = raw archives in the MIRROR layer**, NOT the qlib dataset. The zips land at `<backup-dir>/raw/spot/daily/aggTrades/<SYMBOL>/<YYYY>/<SYMBOL>-aggTrades-<date>.zip` — the **`/<year>/` subdir injected by the mirror exactly as `mirror_path`/`funding_mirror_path` do** (the remote layout is flat under `<SYMBOL>/`; the local mirror adds `/<year>/` to keep per-dir file counts sane). Built via `aggtrades_mirror_path(root, symbol, date)` reusing `aggtrades_archive_parts` so the local layout can't drift from the remote. Validated by sha256 + zip-extractability. The qlib `data-dir` (calendars/instruments/features) is **untouched**. | aggTrades is tick-level — it cannot be a `.day.bin` field. Mirroring the kline/funding mirror logic (incl. the year partition) keeps it consistent and out of the daily dataset; the year subdir matters more here (a 3-month sample is many daily zips, a future full fetch thousands). The future calibration reads the raw zips directly. |
| 4 | **Dedicated `zcrypto data aggtrades PAIRS_FILE --from --to` subcommand** (NOT woven into `download`). It fetches + sha256-validates + stores the raw aggTrades zips for the listed pairs over the window into the mirror; reusable for any pairs/window. | Funding wove into `download` because it became a *dataset field*; aggTrades is a separate raw-archive product with no dataset integration, so overloading `download` would conflate two storage models. A dedicated command keeps `download` (the qlib-dataset builder) clean. |
| 5 | **Bounded sample = a liquidity-spanning subset × a representative multi-month window.** Pairs span book depth: `BTCUSDT`/`ETHUSDT` (deep), `SOLUSDT` (high-mid), `LINKUSDT`/`ATOMUSDT` (mid), `PEPEUSDT` (thin/Tier-3) — ~5-6 pairs. Window ≈ **3 months** covering a calm and a volatile stretch (2024-25, post-PEPE-listing so all tiers have data). Est. ~10-15 GB. Exact pairs/window curated at closeout. | Slippage is liquidity-dependent, so spanning the depth range matters more than exhaustive coverage; ~3 months is ample trades (millions/pair) to later fit a size-vs-slippage curve + maker-fill rate across regimes, at a manageable size. |
| 6 | **Light validation only:** sha256 (the `.CHECKSUM` sibling) + the zip extracts to exactly one CSV. **No** parsing of the millions of trade rows (that's the calibration's job). A missing `.CHECKSUM` → structural check + warning (as klines already do). | Validating integrity doesn't require parsing every trade; full parsing is deferred with the calibration. |

## Component file tree

```
cli/data/
├── binance.py     # MODIFY: aggtrades_archive_parts / aggtrades_zip_url / fetch_aggtrades_archive / fetch_aggtrades_checksum (mirror kline_* ; futures-vs-spot: spot/daily/aggTrades).
├── aggtrades.py   # NEW: validate_aggtrades_zip (sha256 + extracts to one CSV — light, no full row parse) + the mirror-path helper reusing aggtrades_archive_parts.
├── mirror.py      # MODIFY: add aggtrades_mirror_path(root, symbol, date) = root/<rel_dir>/<YYYY>/<name> via aggtrades_archive_parts — the /<year>/ injection mirroring mirror_path/funding_mirror_path exactly.
└── command.py     # MODIFY: add `zcrypto data aggtrades PAIRS_FILE --from --to [--backup-dir]` — fetch + validate + store raw zips to the mirror; write a small sample manifest.
tests/
├── test_data_aggtrades.py   # NEW: archive-parts/URL; validate (sha256 + extractable, missing-checksum warn); FakeSource fetch → stored in the mirror; the manifest.
└── test_data_command.py     # EXTEND: `data aggtrades` arg parsing + dry-run.
README.md                    # MODIFY: Usage — the `zcrypto data aggtrades` subcommand (purpose: a bounded execution-calibration sample; raw-archive store, not the dataset).
```

## Manifest

The fetch writes a small `aggtrades-manifest.json` (in the mirror's aggTrades root) recording the sample: pairs, `[from, to]`, and per-pair fetched-date coverage + total bytes — so the future calibration (and a re-run) know what's available without re-listing, and the sample's intent is documented. Re-running is idempotent (sha256-validated zips already in the mirror are skipped).

## Scope & deferred

- **In:** the aggTrades fetcher (`binance.py` + `aggtrades.py`); the `zcrypto data aggtrades` subcommand; raw-archive mirror storage + light validation + the manifest; acquiring the bounded liquidity-spanning sample; tests.
- **Out (the dedicated `T0004` calibration iteration):** parse the sample into trades; estimate the **size-scaled slippage curve** (slip bps vs order-size/daily-$volume) + **maker-fill probability** (+ the non-fill / taker-chase cost); wire into the backtest cost model (`exchange_kwargs`) and **re-measure** net P&L vs the 12-bps baseline → flips `T0004` resolved.
- **Out (separate topic, if ever):** aggTrades-derived **microstructure features** (realized spread, order-flow imbalance) — a new feature handler, not `T0004`; the fetcher built here would serve it.
- **Out:** the data-free **parametric** slippage term (12 bps + size×volume formula) — separable, needs no aggTrades; tracked on `T0004`.
- **Untouched:** the qlib `data-dir` (dataset), the experiment/recipe/strategy layers, the kline/funding acquisition, `exchange_kwargs`.

## Closeout tasks (authored when the work is real)

- Run `zcrypto data aggtrades` for the finalized liquidity-spanning sample (real fetch into the mirror); record the manifest (pairs × window × bytes) as the "data ready" evidence.
- Flip `T0004` → `partial`: `## Done so far` records the fetcher + the bounded sample (the ingestion path + what's stored); `## Suggested next steps` trimmed to the calibration + application remainder (slippage curve, maker-fill, backtest wiring → resolved) + the separable parametric term.
- README `## Usage`: the `zcrypto data aggtrades` subcommand.
- iter-17 iterations-history entry.
