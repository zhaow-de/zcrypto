---
status: partial
priority: medium
---

# Non-OHLCV features (funding-rate / on-chain / order-book)

## Context — what

The current feature sets — Alpha158, Alpha360, and the iter-13 cross-asset handler —
are all derived exclusively from daily OHLCV klines. Research §5/§14 identifies
additional alpha sources that require data beyond daily spot klines: perpetual-funding
rates (carry signal, crowding proxy), on-chain volume proxies (realized cap velocity,
exchange net-flow), and order-book microstructure (bid-ask depth imbalance, trade-flow
toxicity). None of these can be derived from the existing Binance 1d-kline dataset.

## Why this matters

Each of these data streams encodes information that OHLCV does not: funding rates
reflect the cost of leveraged positioning and can precede price reversions; on-chain
flow distinguishes exchange-bound coins (likely sell pressure) from holder accumulation;
order-book depth captures real-time supply/demand imbalance invisible in daily bars.
Adding even one of these streams as a `feature_config`-selectable handler would test
whether the cross-sectional ranker carries edge on information that competitors without
on-chain / derivatives data cannot replicate. This is the cleanest remaining "different
information" experiment after the OHLCV-family is exhausted.

## Findings so far

Deferred from iter-13 scope (spec `00012`, Decision 9): bounded iter-13 to OHLCV-only
because these features require a new ingest pipeline. The `feature_config` seam shipped
in iter-13 already provides the handler-pluggability needed to wire in a new data source
— the open work is the data ingestion layer, not the experiment scaffold.

Candidate data sources:

- **Funding rates** — Binance `/fapi/v1/fundingRate` (perpetuals); 8h cadence, needs
  daily aggregation (mean / min / max) before joining the kline panel.
- **On-chain** — Glassnode, CryptoQuant, or Token Terminal APIs; typically daily,
  limited free tier; coverage varies by asset.
- **Order book / trade-flow** — Binance aggTrades or depth snapshots; high-volume,
  requires a separate ingest and 1d aggregation step.

## Done so far

**Funding-rate data stream — landed (iter-15, spec `00014`).** Binance USDT-perp funding
history is now a first-class qlib field `$funding` (daily-sum carry, same-day-aligned with
`$close`), woven into every `zcrypto data` subcommand: `download`/`backfill` fetch+write it,
`verify` reports per-coin coverage, `delist` removes it, `rename` carries/merges it across
old→new with the rename gap NaN (`rename` was made field-agnostic for this). The pure
funding layer (`cli/data/funding.py`) handles the spot↔perp mapping (identity +
PEPE→`1000PEPEUSDT` + the MATIC→POL time-split, enforced as a per-date code invariant) and
the **8h/4h-cadence-agnostic** daily aggregation, fetched from the Binance Vision
`futures/um/monthly/fundingRate` archives. A one-time idempotent retrofit
(`cli/data/scripts/backfill_funding.py`) populates `$funding` onto the pre-funding dataset.
Real-data coverage confirmed across all 19 (2020→2026 for the majors; PEPE via
`1000PEPEUSDT`; POL spanning the MATIC→POL rename; `BTCEUR`/`ETHBTC` reference pairs
surfaced as no-/partial-coverage; idempotent re-run wrote nothing). **Data only — the
funding *feature* / recipe / edge-test is not built yet.**

## Suggested next steps

- **Build the funding feature (the immediate next iteration):** a `FundingRateProcessor`
  (following the iter-13 `CrossAssetProcessor` pattern) joining the `$funding` panel to the
  OHLCV feature frame; a `funding_steady` recipe via `feature_config`; then the iter-14
  **multi-seed** holdout A/B against `steady` to judge whether funding carries edge beyond
  the seed-noise band. This is the genuinely-new-signal test the data foundation was built
  for.
- **On-chain proxies** — pursue only if a free source actually covers our 19 (CoinMetrics
  Community is the candidate; coverage for newer alts like PEPE/APT/ARB needs a check).
  Daily active-address / exchange-flow metrics as a `feature_config` handler.
- **Order book / trade-flow** — Binance aggTrades / depth; high-volume, ~forward-only,
  relevant only at higher frequency; defer until a daily strategy warrants it.
