# iter-47 — Stage-2: cross-sectional momentum tilt (`momentum_tilt`) (design)

**Goal:** test the one tilt direction not yet cleanly probed — pure **cross-sectional price momentum**
(overweight the held basket's recent relative winners) — motivated by the night's consistent finding that
*fade-strength* signals lose (the sample is momentum-dominated). **Success bar:** mean delta-vs-`beta_null` > 0
with bootstrap CI clearing 0. Decisions `.tmp/decisions.md` iter-047.

## Context

Across iter-40/43/46 every signal that *fades strength* (basis-crowding −0.18, smart-money-follow −0.07,
NVM-de-risk −0.41) underperformed `beta_null` — the 2022-2025 regime rewards momentum. Yet the momentum forms
tried so far don't isolate pure cross-sectional price momentum: per-asset TSMOM (iter-35-37) was *time-series*
(refuted), and OI-confirmation (iter-41/42) was momentum-among-up-movers *gated by OI* (~neutral). This tests
the clean version: among the held basket, overweight coins with the strongest recent relative return. It
directly asks whether there's exploitable cross-sectional momentum **beyond** the market-beta that
`beta_null`'s 200d gate already captures. A null result is itself informative — it would mean the edge is
market-beta-timing (the gate), not cross-sectional selection.

## Design — one variable vs `beta_null`

Reuse the cross-sectional tilt machinery (`_apply_cross_sectional_tilt(sign=+1)`, strictly-prior lookup, no
look-ahead), with a trailing-return signal.

- **Signal (`_build_momentum_signal`):** read the `$close` wide panel for `weight_universe`; trailing
  `lookback`-day return `mom = $close / $close.shift(momentum_lookback) − 1` (a date×instrument panel; causal —
  row d uses closes ≤ d). NaN in warmup / where close is NaN.
- **Strategy (`VolWeightedRegimeStrategy`):** add `momentum_tilt: bool = False` (off → back-compatible),
  `momentum_lookback: int = 30`, `momentum_tilt_k: float = 1.0`. In `generate_target_weight_position`, after
  `w = inverse_vol_weights(vols)`: if `momentum_tilt`, take the **strictly-prior** `mom` row (same no-look-ahead
  discipline as the vol/OI-div lookups), cross-sectionally z-score across the held `names`, and
  `w_i *= exp(+momentum_tilt_k·z_i)` (UP-weight recent winners), renormalize. NaN → tilt 1.0. Reuse
  `_apply_cross_sectional_tilt(..., sign=+1.0)`. Injectable `_momentum_signal` seam. `momentum_tilt=False` ⇒
  byte-identical to today.
- **`momentum_tilt` recipe:** `beta_null`'s book + `momentum_tilt=True`, `momentum_lookback=30`,
  `momentum_tilt_k=1.0`. Frozen otherwise.

## Validation

`zcrypto stress --recipe momentum_tilt --null beta_null` → per-window + across-window delta-vs-`beta_null` +
bootstrap CI + CPCV. Read cost-adjusted (momentum tilts raise turnover — watch the cost drag).

## Success / kill

- **Win:** mean delta > 0, CI clears 0 → cross-sectional momentum adds selection edge over inverse-vol; next
  tune `lookback`/`k`, try a vol-scaled momentum, or a long-horizon variant.
- **Null/negative:** no exploitable cross-sectional momentum beyond the market-beta gate → the edge is
  market-timing, not selection. Record it; with both fade-strength AND momentum tilts exhausted, the
  cross-sectional-selection channel on price data is ~closed (the remaining levers are `beta_null`'s own knobs
  and the parked credentialed/1h threads).

## Testing (TDD)

- **momentum-signal unit:** `_build_momentum_signal` = `close/close.shift(lookback) − 1`, causal
  (truncation-invariant); NaN in warmup.
- **tilt behavior** (inject `_momentum_signal`): a high-momentum coin (z>0) up-weighted vs inverse-vol, a
  low-momentum coin down-weighted, a NaN coin neutral; weights sum to 1; no look-ahead (strictly-prior).
- **`momentum_tilt` drift-guard** — `beta_null` + exactly the three momentum kwargs.
- **back-compat** — `momentum_tilt=False` byte-identical; the other overlays/tilts untouched.
- **stress A/B** — redis-gated.

## Closeout

`docs/iterations-history.md` iter-47 entry with the delta-vs-`beta_null` verdict; if null, record that the
price cross-sectional-selection channel (both fade-strength and momentum) is exhausted and the edge is
market-beta-timing.
