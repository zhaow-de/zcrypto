# iter-38 — Stage-2 data: free derivatives-positioning ingestion (OI, long-short, basis) (design)

**Goal:** ingest the **free** Binance futures derivatives streams — open interest, long-short ratios, and
perp-spot basis — as new qlib fields, so Stage-2 derivatives-positioning **signals** (OI-price divergence,
basis extremes, funding dispersion, long-short contrarian) can be built + A/B'd vs `beta_null` in the
*next* iteration. **This iteration is data only — no signal, no edge claim.** (Decisions iter-038; user
chose ingest-richer-first over funding-only.)

## Context

Per-asset TSMOM is exhausted (iter-35/36/37). The orientation (§3 #2) ranks derivatives-positioning as the
**strongest genuinely-free new information**. The `$funding` stream + aggTrades already land via the
Phase-1 pipeline (`cli/data/binance.py`, `cli/data/pipeline.py`); OI / long-short / basis do not. This
iteration extends that pipeline with the remaining free futures archives, reusing the funding-ingestion
pattern end-to-end (download / backfill / verify / delist / rename lifecycle, the spot↔perp symbol map,
same-day `$close` alignment, NaN before a perp's launch).

## Data sources (free, `data.binance.vision`)

- **Futures `metrics/` (daily):** `futures/um/daily/metrics/<PERP>/<PERP>-metrics-<YYYY-MM-DD>.zip` — columns
  `sum_open_interest`, `sum_open_interest_value`, `count_toptrader_long_short_ratio`,
  `sum_toptrader_long_short_ratio`, `count_long_short_ratio`, `sum_taker_long_short_vol_ratio`. ⚠
  **daily-granularity only** (intraday positioning isn't free; accrues live going forward).
- **Basis:** perp-spot basis from `markPriceKlines` / `premiumIndexKlines` (or mark vs index) — daily basis
  = `(mark − index)/index` (or the archived premium index). Confirm the exact archive + column layout against
  `data.binance.vision` during implementation (a probe/verify step, not assumed).

## New qlib fields (proposed — finalize at impl)

`$oi`, `$oi_value`, `$ls_global` (global account long/short), `$ls_top` (top-trader), `$taker_ratio`
(taker buy/sell volume), `$basis`. Same-day aligned with `$close`; NaN where a coin has no perp (or before
its perp launch), exactly like `$funding`. Naming + the precise set finalized against the archive columns.

## Pipeline integration (mirror funding)

- `cli/data/binance.py`: add `metrics_archive_parts` / `metrics_url` + `fetch_metrics_archive` (and the
  basis equivalents), mirroring `funding_archive_parts` / `fetch_funding_archive`.
- `cli/data/klines.py` (or a sibling decoder): decode the metrics/basis zips → normalized daily rows.
- `cli/data/pipeline.py` + `cli/data/config.py`: add the new fields to `FIELDS`; thread them through
  `download` / `backfill` / `verify` (per-coin coverage report) / `delist` / `rename`, same as `$funding`.
- Spot↔perp mapping: reuse the existing map (incl. `PEPE→1000PEPEUSDT`, the MATIC→POL split); coins without a
  perp read NaN.

## Validation / non-goals

- **Non-goals:** the derivatives *signals* + the A/B (iter-39); intraday OI/long-short (not free); any edge claim.
- **Risk:** the metrics/basis archive layout may differ from funding's — verify against a live sample early;
  some covered coins may have short or gappy metrics history (handle like funding's NaN/partial coverage).
- Honesty: the orientation flags the funding edge as **decaying** (full-sample Sharpe ~6.4 → ~4 (2024) →
  negative (2025)) — historicals are a ceiling; this iteration only lands the *data*, the signal iteration
  must read cost-adjusted, regime-aware verdicts.

## Testing (TDD)

- Decoder unit tests on a **synthetic** metrics/basis zip (known rows → normalized fields), mirroring the
  kline/funding decoder tests — no network.
- Pipeline integration: a small fixture exercising `download`/`verify` surfacing the new fields + their
  per-coin coverage; NaN-before-launch respected.
- `verify` reports the new fields' coverage per coin.

## Closeout

`README.md` data-section update (the new `$`-fields ride the normal data lifecycle); `docs/iterations-history.md`
iter-38 entry (data landed + coverage); the signal work tracked as iter-39 (a new open-topic or the
iterations-history next-step).
