# iter-39 — Stage-2: perp-spot-basis "froth" de-risk overlay (`basis_froth`) (design)

**Goal:** test whether a **derivatives-positioning** signal — the perp-spot **basis** ("froth" / leverage
crowding) — improves cost-adjusted Sharpe when composed as a de-risk overlay on `beta_null`. **Success bar:**
positive mean delta-vs-null whose bootstrap CI clears 0, on the CPCV/stress distribution. First test of the
derivatives data the iter-38 ingestion unlocked. Decisions `.tmp/decisions.md` iter-039.

## Context

Per-asset TSMOM is exhausted (iter-35/36/37); the user pivoted Stage-2 EV to **derivatives-positioning**
(orientation §3 #2). The iter-38 ingestion landed `$oi`, `$oi_value`, `$ls_top`, `$ls_global`,
`$taker_ratio`, `$basis`. The orientation flags **funding as decaying** but `$basis` (perp premium over the
index) as a fresher leverage/crowding proxy: a high basis = leveraged longs paying up = froth = elevated
mean-reversion-DOWN risk; backwardation = fear. iter-35/36/37 also taught that the market gate is robust —
**add, don't replace**. So this composes a basis-froth de-risk overlay ON TOP of `beta_null`.

## Design — one variable vs `beta_null`

Keep `beta_null`'s book verbatim (BTC-200d gate, inverse-vol top-10 liquid, `vol_target=0.50`, `vip2_bnb`,
DummyRegressor); **add** a basis-froth exposure multiplier composed into `VolWeightedRegimeStrategy._mult_for`.

- **Strategy (`VolWeightedRegimeStrategy`):** add `froth_field: str | None = None` (off by default →
  back-compatible), `froth_lookback: int = 90`, `froth_z_threshold: float = 1.5`, `froth_derisk_mult:
  float = 0.0`. When `froth_field` is set, a lazy `_build_froth_signal()` (mirroring `_build_vol_panel`)
  reads `D.features(weight_universe, [froth_field])`, takes the **cross-sectional median** across the
  universe per date, and computes a **rolling z-score** over `froth_lookback` (uses dates ≤ d only — no
  look-ahead, same timing as the regime gate's through-date-d close data). In `_mult_for(date)`: after the
  regime multiplier, if `froth_z(date) > froth_z_threshold` → multiply the exposure by `froth_derisk_mult`
  (0.0 = full cash when frothy). An injectable `_froth_signal` seam for tests, like `_exposure`/`_close_panel`.
  `froth_field=None` ⇒ byte-identical to today (beta_null, the tsmom recipes unaffected).
- **`basis_froth` recipe:** `beta_null`'s book + `froth_field="$basis"`, `froth_lookback=90`,
  `froth_z_threshold=1.5`, `froth_derisk_mult=0.0`. Everything else frozen, so the A/B isolates the overlay.

## Validation

`zcrypto stress --recipe basis_froth --null beta_null` → per-window + across-window delta-vs-null with the
paired bootstrap CI + the CPCV distribution. Read cost-adjusted, not gross.

## Success / kill

- **Win:** mean delta-vs-null > 0, CI clears 0 → the basis-froth overlay times de-risking better than (or
  adds to) the price-only BTC-200d gate; the first Stage-2 improvement. Next: tune the threshold/lookback,
  try a graded (not binary) de-risk, add backwardation risk-on.
- **Null/negative:** the overlay doesn't beat `beta_null` (basis-froth doesn't add timing value over the
  200d gate). A valid finding — record it; the next derivatives signal (OI-price divergence, cross-sectional
  funding/basis tilt) is the follow-up. Any "shelve derivatives-positioning" call is parked for the human.

## Testing (TDD)

- **froth overlay unit** (inject `_froth_signal` + `_exposure`/`_close_panel`): a date with froth_z above
  threshold → exposure ×`froth_derisk_mult` (cash at 0.0); below threshold → regime multiplier unchanged;
  `froth_field=None` → byte-identical to today. No look-ahead (the z-score at d uses only dates ≤ d).
- **`basis_froth` drift-guard** — `beta_null`'s frozen params + `froth_field="$basis"` + the froth params; the
  ONLY strategy-kwargs delta vs `beta_null` is the froth set.
- **stress A/B** — redis-gated: `stress --recipe basis_froth --null beta_null` writes the delta keys.

## Closeout

`docs/iterations-history.md` iter-39 entry with the measured delta-vs-null verdict; update the derivatives
follow-up trail; if negative, name the next derivatives signal to try.
