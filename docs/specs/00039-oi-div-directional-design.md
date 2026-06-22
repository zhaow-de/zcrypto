# iter-42 — Stage-2: directional OI-divergence tilt (`oi_divergence_directional`) (design)

**Goal:** refine iter-41's neutral OI-divergence tilt by making the signal **directional** — favor OI-confirmed
**up-moves** only, and stop up-weighting confirmed *downtrends* (which a long-only basket should not favor).
**Success bar:** mean delta-vs-null > 0 with bootstrap CI clearing 0 — and, minimally, a clear improvement
over iter-41's +0.008. Decisions `.tmp/decisions.md` iter-042; the live thread from `T0023`.

## Context

iter-41's OI-divergence tilt was NEUTRAL (+0.008; helped 2024, hurt 2023). Its confirmation =
`sign(price_chg)·oi_chg` is **symmetric**: a "confirmed downtrend" (price↓ + OI↓) scores **positive** and gets
**up-weighted**, so in a long-only basket the tilt overweights *falling* coins — more of them in choppy 2023
(the hurt) than in the 2024 bull. (Literal "regime-conditioning" was analysed + rejected in the decision log:
gate-state conditioning is a no-op since the tilt only affects returns when invested; trend-strength doesn't
separate 2023 from 2024 — BTC was well above its 200d in both.) The fix isolates the intended edge: among the
held basket, reward rising OI **only where price is also rising** (new money confirming an up-move), penalize
weak rallies (price↑ + OI↓), and leave falling coins untilted.

## Design — one flag vs iter-41's tilt

Reuse the iter-41 OI-divergence machinery (`_build_oi_div_signal`, `_apply_cross_sectional_tilt(sign=+1)`,
strictly-prior lookup, no look-ahead). Add ONE flag that changes only the **confirmation construction**.

- **Strategy (`VolWeightedRegimeStrategy`):** add `oi_div_directional: bool = False` (off → iter-41 behavior).
  In `_build_oi_div_signal`, when `oi_div_directional` is True: `confirmation_i = oi_chg_i` **where**
  `price_chg_i > 0`, else **NaN**. (When False: the iter-41 `sign(price_chg)·oi_chg`.) The existing tilt then
  z-scores the confirmation across the **non-NaN** held names (the up-movers), `w *= exp(+k·z)` up-weights
  rising-OI up-movers / down-weights weak rallies, and **NaN → tilt 1.0** leaves the down-price coins neutral
  (untilted) — exactly the directional behavior, with no new tilt code. `oi_divergence=False` ⇒ byte-identical
  to today. No look-ahead: same strictly-prior discipline as iter-41.
- **`oi_divergence_directional` recipe:** `beta_null`'s book + `oi_divergence=True`, `oi_div_directional=True`,
  `oi_div_lookback=14`, `oi_div_tilt_k=1.0`. Everything else frozen.

## Validation

`zcrypto stress --recipe oi_divergence_directional --null beta_null` → per-window + across-window delta-vs-null
with the paired bootstrap CI + the CPCV distribution. Compare to iter-41's +0.008 and to `beta_null`.

## Success / kill

- **Win:** mean delta > 0, CI clears 0 → directional OI-confirmation adds edge; tune `L`/`k` next, then consider
  stacking with the regime gate or a different field.
- **Null/negative or no better than iter-41:** the OI-confirmation edge is weak/absent even directional. Record
  it; remaining derivatives probes (`$taker_ratio` / `$ls_*` contrarian tilt, or a graded combination) are the
  follow-ups in `T0023`. Only after those would "shelve derivatives-positioning" be evidenced (parked for the human).

## Testing (TDD)

- **directional-signal unit** (inject `_oi_div_signal` is bypassed — test `_build_oi_div_signal` directly or via
  an injected `$close`/`$oi` panel): for an up-price coin, confirmation = its `oi_chg`; for a down-price coin,
  confirmation is NaN (→ neutral tilt). With `oi_div_directional=False`, confirmation = `sign(price_chg)·oi_chg`
  (iter-41, unchanged).
- **tilt behavior** (inject `_oi_div_signal` directly): an up-mover with high OI z>0 is up-weighted, an up-mover
  with OI z<0 down-weighted, a down-price coin (NaN) neutral; weights sum to 1; no look-ahead.
- **`oi_divergence_directional` drift-guard** — `beta_null` + exactly the four oi-div kwargs (incl.
  `oi_div_directional=True`); the iter-41 `oi_divergence_tilt` recipe (directional=False) still resolves.
- **stress A/B** — redis-gated.

## Closeout

`docs/iterations-history.md` iter-42 entry with the measured delta-vs-null verdict (vs both `beta_null` and
iter-41's +0.008); update `T0023`; pick the next OI-divergence refinement or the next derivatives probe.
