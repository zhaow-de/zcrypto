# iter-43 — Stage-2: smart-money L/S divergence tilt (`smart_money_tilt`) (design)

**Goal:** test a **genuinely different** derivatives-positioning signal — top-trader vs retail long/short
positioning (`$ls_top` / `$ls_global`) — as a cross-sectional weighting tilt on `beta_null`. **Success bar:**
mean delta-vs-null > 0 with bootstrap CI clearing 0. Decisions `.tmp/decisions.md` iter-043; `T0023`.

## Context

Price-derived positioning is ~tapped: `$basis` is dead (both forms, iter-39/40) and OI-divergence is neutral
(iter-41/42, only a bull-regime effect). The L/S ratios are a **different mechanism** — *who* is positioned
how: `$ls_top` is the top-trader (larger accounts ≈ "smart money") long/short ratio, `$ls_global` the global
account (retail-weighted) ratio. The classic edge: when smart money is positioned **more long than the
crowd**, that name tends to outperform (smart money leads); when retail is crowded long but top-traders
aren't, it tends to underperform. This is a cross-sectional **selection** tilt, the form that fits `beta_null`.

## Design — one variable vs `beta_null`

Reuse the cross-sectional tilt machinery (`_apply_cross_sectional_tilt(sign=+1)`, strictly-prior lookup, no
look-ahead). The signal is a positioning **level** (not a change), so no lookback.

- **Signal (`_build_smart_money_signal`):** read `$ls_top` and `$ls_global` wide panels for `weight_universe`.
  `smart_div = $ls_top / $ls_global` (a date×instrument panel): >1 ⇒ top-traders relatively more long than the
  crowd. NaN where either field is NaN (no perp / pre-launch / a 404 gap). (The ratio normalizes the two
  ratios' different scales.)
- **Strategy (`VolWeightedRegimeStrategy`):** add `smart_money: bool = False` (off → back-compatible),
  `smart_money_tilt_k: float = 1.0`. In `generate_target_weight_position`, after `w = inverse_vol_weights(vols)`:
  if `smart_money`, take the **strictly-prior** `smart_div` row (same no-look-ahead discipline as the vol /
  crowding / OI-div lookups), cross-sectionally z-score across the held `names`, and `w_i *= exp(+k·z_i)`
  (UP-weight coins where smart money is relatively more long), renormalize. NaN → tilt 1.0 (neutral). Reuse
  `_apply_cross_sectional_tilt(..., sign=+1.0)`. `smart_money=False` ⇒ byte-identical to today. Injectable
  `_smart_money_signal` seam for tests.
- **`smart_money_tilt` recipe:** `beta_null`'s book + `smart_money=True`, `smart_money_tilt_k=1.0`. Frozen otherwise.

## Validation

`zcrypto stress --recipe smart_money_tilt --null beta_null` → per-window + across-window delta-vs-null with the
paired bootstrap CI + the CPCV distribution. Read cost-adjusted, not gross.

## Success / kill

- **Win:** mean delta > 0, CI clears 0 → smart-money positioning predicts relative returns; tune `k`, try the
  *divergence change* (smart money increasing long vs retail), or combine with OI-confirmation.
- **Null/negative:** L/S positioning adds no edge either. **Then all the cheap derivatives probes
  (basis ×2, OI ×2, L/S) are ~tapped** — derivatives-positioning looks like a weak/absent Channel-A edge for
  this universe net of costs, and the "shelve derivatives-positioning → BTC→alt lead-lag (`T0020`)" call
  becomes **well-evidenced**, recorded as **parked for the human** (high-stakes, not auto-ratified by the loop).

## Testing (TDD)

- **signal unit** (`_build_smart_money_signal` on an injected `$ls_top`/`$ls_global` panel or a stub): a coin
  with high `$ls_top`/`$ls_global` ratio scores high; NaN where either input is NaN.
- **tilt behavior** (inject `_smart_money_signal`): a high-ratio coin (z>0) up-weighted, a low-ratio coin
  down-weighted, a NaN coin neutral; weights sum to 1; no look-ahead (strictly-prior).
- **`smart_money_tilt` drift-guard** — `beta_null` + exactly the two smart-money kwargs.
- **back-compat** — `smart_money=False` byte-identical; the OI-div / crowding tilts untouched (the shared
  helper still works).
- **stress A/B** — redis-gated.

## Closeout

`docs/iterations-history.md` iter-43 entry with the delta-vs-null verdict; update `T0023`; if negative,
record that the cheap derivatives probes are tapped and restate the parked shelve/pivot call.
