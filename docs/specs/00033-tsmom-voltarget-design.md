# iter-35 — Stage-1: per-asset TSMOM + vol-targeting (`tsmom_voltarget`) (design)

**Goal:** test the orientation's highest-EV Phase-2 bet (`T0019`) — a **per-asset** trend-following book
(each coin long/cash on its OWN trend) with inverse-vol weighting and vol-targeting — A/B'd against the
`beta_null` yardstick. **Success bar:** a positive delta-vs-null (`tsmom_voltarget − beta_null`) whose
stationary-bootstrap CI clears 0 across the OOS windows; i.e. per-asset trend selection beats the
market-gated basket net of costs. (Decisions: `.tmp/decisions.md` iter-035.)

## Context

`beta_null` (iter-34) gates the WHOLE basket on **BTC's** 200d trend (full cash in a market bear) + inverse-vol
weights the top-10-liquidity coins; its yardstick is mean OOS Sharpe ≈ 0.38. The Phase-2 orientation
(`docs/research/03.phase2-orientation.md` §3 bucket #1) names **time-series momentum + vol-targeting** as the
most-replicated premium and the likely new core: hold each coin on its *own* trend rather than the market's.
This iteration isolates exactly that one change.

## Design — one variable vs `beta_null`

Keep `beta_null`'s book verbatim (top-10-by-liquidity PIT monthly universe, inverse-vol weighting,
`vol_target=0.50`, `vip2_bnb` costs, `DummyRegressor`, label/segments) and change **only the gate**: replace
the market BTC-200d binary gate with **per-asset trend selection**.

- **Per-asset trend gating.** Extend `VolWeightedRegimeStrategy` (`cli/experiment/strategies/regime.py`) with a
  `trend_window: int | None = None` kwarg (default `None` ⇒ unchanged, back-compatible). When set: (a) the
  market regime multiplier is disabled (no BTC full-cash gate — `_mult_for` → 1.0), and (b) a **per-asset
  trend filter** is added to the held set — drop any name whose latest close is **≤ its own `trend_window`-day
  SMA** (computed lazily from `D.features($close)`, mirroring `_build_vol_panel`). The surviving names are
  inverse-vol weighted as today. So the held set per rebalance = liquidity-members ∩ {close > own SMA(window)};
  in a full bear every coin is below its SMA ⇒ full cash (the per-asset analogue of the market gate's defense).
- **`tsmom_voltarget` recipe** (`cli/experiment/recipes/tsmom_voltarget.py`): a copy of `beta_null` with
  `trend_window=100` added to the strategy kwargs (the a-priori window — decisions iter-035), everything else
  frozen identical so the A/B isolates per-asset-vs-market gating.

## Validation

`zcrypto stress --recipe tsmom_voltarget --null beta_null` → per-window + across-window **delta-vs-null** with
the paired stationary-bootstrap CI (the iter-34 harness), plus the CPCV path distribution. Read the
**cost-adjusted** delta, not gross. The verdict is the across-window mean delta + whether its CI clears 0.

## Success / kill

- **Win:** mean delta-vs-null > 0 with a CI clearing 0 → per-asset TSMOM is a real improvement over the
  market-gated null; record it, and the next iteration tunes the window / adds intraday realized-vol sizing.
- **Null/負:** delta ≈ 0 or its CI straddles 0 → per-asset gating doesn't beat the market gate on this data;
  record the honest verdict and park the window-sweep + the 4h/intraday-vol variant as follow-ups (do NOT
  grid-search the window to the holdout).

## Non-goals (parked, per the loop boundary + the human's launch directive)

- Spending the reserved-holdout "look" or committing the trial-budget deflation (irreversible — human's call).
- A "permanent kill/shelve" of the whole TSMOM/Channel-A direction (high-stakes — proposed, not ratified).
- Intraday (4h/1m realized-vol) sizing and the window sweep — reversible follow-ups, but out of this iteration's
  one-variable scope; capture as next-steps.

## Testing (TDD)

- **per-asset trend filter** — unit (inject a synthetic close panel + schedule): with `trend_window=100`, the
  held set is exactly liquidity-members ∩ {close > SMA}; a coin below its SMA is dropped; `trend_window=None`
  is byte-identical to today's `VolWeightedRegimeStrategy` (regression).
- **`tsmom_voltarget` drift-guard** — frozen params == `beta_null`'s except `trend_window=100` + no market gate.
- **stress A/B** — redis-gated: `stress --recipe tsmom_voltarget --null beta_null` writes the delta keys.

## Closeout

- `README.md` Usage: note the new recipe (and the `trend_window` strategy knob) if user-facing.
- `docs/iterations-history.md`: the iter-35 entry with the measured delta-vs-null verdict.
- Open-topics: capture the window-sweep + intraday-vol follow-ups.
