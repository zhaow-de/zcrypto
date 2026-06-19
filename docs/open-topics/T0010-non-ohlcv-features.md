---
status: open
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

## Suggested next steps

- Pick the highest-signal / lowest-ingest-cost stream first: **funding rates** are
  available via Binance's own API (no third-party dependency) and aggregate cleanly to
  daily (mean funding, cumulative 8h counts, spread between spot and perp close).
- Extend `zcrypto data` with a `data download-funding` subcommand (or a `--funding` flag
  on `data download`) that fetches and stores funding-rate time series alongside klines.
- Implement a `FundingRateProcessor` (following the `CrossAssetProcessor` pattern from
  iter-13) that joins the funding panel to the OHLCV feature frame.
- Wire a `funding_steady` recipe using `feature_config` pointing at the new handler and
  run a clean A/B against `steady`.
- Repeat for on-chain proxies if funding-rate results are promising.
