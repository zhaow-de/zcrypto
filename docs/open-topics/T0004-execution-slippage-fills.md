---
status: partial
priority: medium
---

# Realistic execution: size-scaled slippage + maker-fill probability

## Context — what

The skeleton (spec `00006`) models fees (12 bps round-trip, VIP2+BNB) but assumes
frictionless fills at close with no slippage and 100% maker fills. The roadmap's
cost baseline is "12 bps + a size-scaled slippage term," and the low/zero-fee
economics depend on maker limit orders actually filling.

## Why this matters

Research §6/§8/§13 — slippage and unfilled maker orders are where frictionless
backtests diverge from live P&L; thin USDC books (Tier-3, PEPE) slip materially.
Ignoring this overstates net returns, especially as turnover rises.

## Findings so far

Deferred from the experiment skeleton (spec `00006`). Fee presets already live in
the recipe; slippage/fill realism need an aggTrades sample (absent from the daily
dataset). References: research §6 (trade/aggTrade), §8 (fees), §13 Stage 3.

**Parametric size-scaled slippage (iter-12, spec `00011`).** Research §13 Stage 2
specifies the cost baseline as "12 bps + a size-scaled slippage term" (bps
proportional to order size / daily $-volume). This parametric term is a scaffold
extension (a new cost-model argument to the recipe/backtest) that is **separable**
from the data-gated aggTrades maker-fill path — it requires no new data, only a
formula applied to the daily-kline volume already in the dataset. It was identified
during iter-12 scoping but deferred; the aggTrades fill-realism work (the harder
data-gated part) remains the primary open item.

## Done so far

**aggTrades data + ingestion path landed (iter-17, spec `00016`).** A first-class,
reusable aggTrades fetcher now lives in `cli/data`: `zcrypto data aggtrades PAIRS_FILE
--from --to` fetches `data.binance.vision` aggTrades zips, sha256-validates them, and
stores them in the raw mirror at `<backup-dir>/raw/spot/daily/aggTrades/<SYMBOL>/<YYYY>/…`
(the qlib dataset is untouched — aggTrades is tick-level, a calibration input, not a
panel). DRY: the fetch+checksum core is the shared `fetch_checksummed_zip` extracted from
`data download` (download byte-identical). A **bounded, liquidity-spanning sample** was
acquired — `BTCUSDT`/`ETHUSDT` (deep) → `SOLUSDT` (high-mid) → `LINKUSDT`/`ATOMUSDT` (mid)
→ `PEPEUSDT` (thin), over `2024-12-01..2025-02-28` (90 days each, ~6 GB), with an
idempotent `aggtrades-manifest.json` documenting the present sample. **Data only** — the
slippage/maker-fill *calibration* and the backtest wiring are not built yet.

## Suggested next steps

- **Calibrate from the sample** (the dedicated `T0004` iteration): parse the aggTrades
  zips → estimate the **size-scaled slippage curve** (slip bps vs order-size / daily-$volume)
  + the **maker-fill probability** (and the taker-chase / missed-trade cost of non-fills).
  The fetcher extends to a wider window via an idempotent re-run if more data is needed.
- **Fold into the backtest cost model** (`exchange_kwargs`) and re-measure net P&L vs the
  12-bps baseline → flips `T0004` → resolved.
- **The separable parametric term** (iter-12 / §13 Stage 2: "12 bps + size×volume", no
  aggTrades needed) can land independently — a formula on the daily-kline volume already
  in the dataset.
