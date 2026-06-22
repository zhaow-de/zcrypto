---
status: open
---

# Per-asset TSMOM gating — window, anti-whipsaw, and intraday-vol follow-ups

## Context — what

iter-35 (`T0019` Stage 1) tested replacing `beta_null`'s market BTC-200d gate with **per-asset** trend
gating (each coin long/cash on its own **100d** SMA), keeping the rest of `beta_null`'s book. It was
**refuted**: mean OOS Sharpe ≈ −0.05 vs the null's +0.38 (mean delta-vs-null −0.427), with the damage
concentrated in the bear years (2022 −0.79, 2025 −0.82) — the per-asset 100d gate re-enters individual
coins on bear dead-cat bounces where the single BTC-200d gate stays cleanly in cash (the Phase-1
"faster/more-granular gates whipsaw" lesson at the per-asset level). This topic tracks the remaining
per-asset-TSMOM levers worth testing before the sub-channel is judged dead.

## Why this matters

Per-asset trend-following is the orientation's named highest-EV Channel-A bet (`docs/research/03.phase2-orientation.md`
§3 #1) — the most-replicated systematic premium. One window (100d) losing to the market gate is *not* the
same as the premium being absent here; the loss looks like a **whipsaw/granularity** problem, which has
concrete, cheap, reversible fixes (a slower window, a confirmation filter, a better vol estimator). Ruling
those out is what licenses the high-stakes "shelve per-asset gating" call (parked for an attended session).

## Findings so far

- iter-35: per-asset **100d** SMA gating loses to `beta_null` (market BTC-200d gate), mean delta −0.427,
  bear-year whipsaw. The reusable `trend_window` mode on `VolWeightedRegimeStrategy` + the `tsmom_voltarget`
  recipe are merged and ready to parameterize. The market gate's parsimony (one clean BTC signal, full
  cash in a market bear) beat per-asset granularity.

## Suggested next steps

- **Per-asset 200d window (iter-36, the immediate next A/B):** `trend_window=200`, matching `beta_null`'s
  gate window — isolates "per-asset vs market gate at the *same* speed." If it ties the market gate,
  per-asset granularity is neutral; if it still loses, granularity itself whipsaws. Reuse the existing mode
  (just a new recipe).
- **Anti-whipsaw confirmation filter:** require N consecutive days above/below the SMA (or a hysteresis
  band) before flipping a coin's exposure — directly targets the dead-cat-bounce re-entry that sank the
  100d gate (mirrors the parked `T0017` anti-whipsaw lever, now at the per-asset level).
- **Intraday realized-vol sizing (orientation §3 #4):** feed the inverse-vol weighting an intraday
  realized-vol estimate (1m→aggregated) instead of daily-range vol — a low-risk multiplier on whatever
  trend rule survives. Requires the 1h/1m kline ingestion path (shared with `T0020`).
- **Kill condition (parked — human ratifies):** if 200d AND the confirmation filter both fail to beat the
  null, treat per-asset trend gating as a dead sub-channel and redirect Stage-1 EV to derivatives-positioning
  (orientation §3 #2) — a high-stakes pivot for an attended session, not the loop.
