---
status: resolved
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

## Resolution (iter-19, spec/plan `00018`)

Calibrated realistic execution costs are now the **default** experiment cost model, with a
`--fees-only` opt-out baseline. From the iter-17 aggTrades sample (`calibrate_execution.py`,
540 pair-days): qlib `impact_cost` **85.1** (tiers diverge deep 39.3 / mid 86.0 / thin 130.1 —
liquidity-dependent), maker-fill rate **~0.51**, `maker_fill_haircut` **~2.2 bps/side** (folded
into the fee fractions; no custom executor — qlib has no fill hook). Single representative scalars
wired (qlib's exchange knobs are scalars); per-tier `(c,f,s)` recorded as analysis.

**Verdict (5 recipes, realistic vs `--fees-only`, 16-seed holdout):** realistic costs add a small,
consistent drag — paired cost-adjusted Sharpe −0.012 (skeleton −0.037), realistic uniformly worse.
**At the $10k account slippage is negligible** (orders ≪ daily $-volume → `(order/bar_vol)²` ≈ 0);
the **maker-fill haircut dominates**, scaling with turnover (skeleton ≈+2 pp annualized; crossasset
≈+0.8 pp). The iter-12 parametric "12 bps + size×volume" term is subsumed by the calibrated
`impact_cost`. Parked: a custom Exchange/executor for per-tier slippage + explicit per-order fill
probability (see [[T0014-force-liquidate-on-delisting]] for the related fills-realism direction);
aggTrades-derived microstructure features. A measurement quirk was surfaced — the `--seeds` holdout
`ending_value` is gross (pre-cost) while Sharpe/PSR are net — a candidate follow-up.
