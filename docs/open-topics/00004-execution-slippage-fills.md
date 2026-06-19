---
status: open
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

## Suggested next steps

- Pull a representative aggTrades window; estimate size-scaled slippage vs daily
  volume.
- Model maker-fill probability (and the taker-chase / missed-trade cost of
  non-fills).
- Fold into the backtest cost model; validate against the 12 bps baseline.
