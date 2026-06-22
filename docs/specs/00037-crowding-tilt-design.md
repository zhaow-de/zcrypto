# iter-40 — Stage-2: cross-sectional basis-crowding weighting tilt (`basis_tilt`) (design)

**Goal:** test whether a **cross-sectional** derivatives-crowding signal — tilting `beta_null`'s inverse-vol
basket *away from* over-crowded (high perp-premium) coins and *toward* under-crowded (backwardated) ones —
improves cost-adjusted Sharpe vs `beta_null`. **Success bar:** positive mean delta-vs-null whose bootstrap
CI clears 0. Decisions `.tmp/decisions.md` iter-040; follow-up to `T0023`.

## Context

iter-39 showed `$basis` as a binary market-**timing** gate fails (de-risks in bulls). This tests the
orientation's (§3 #2) **core** derivatives-positioning form instead: a cross-sectional **selection/weighting**
signal — crowded names (high perp premium = leveraged longs paying up) tend to underperform the
under-crowded. It composes with `beta_null`'s inverse-vol weighting (a *tilt*, not a gate), so it cannot
repeat iter-39's "de-risk in bulls" failure. Funding is decaying (orientation), so `$basis` is the probe.

## Design — one variable vs `beta_null`

Keep `beta_null`'s book verbatim (BTC-200d gate, top-10-liquidity, `vol_target=0.50`, `vip2_bnb`,
DummyRegressor) and the inverse-vol weights; **add** a multiplicative crowding tilt in
`VolWeightedRegimeStrategy.generate_target_weight_position`, applied to the inverse-vol weights `w`.

- **Strategy (`VolWeightedRegimeStrategy`):** add `crowding_field: str | None = None` (off → back-compatible)
  and `crowding_tilt_k: float = 1.0`. A lazy `_crowding_panel` (wide date×instrument, mirroring `_vol_panel`)
  reads `D.features(weight_universe, [crowding_field])`. In `generate_target_weight_position`, after
  `w = inverse_vol_weights(vols)`: take the **strictly-prior** crowding row (`panel.loc[index < t].iloc[-1]`
  — NO look-ahead, same discipline as the vol lookup), cross-sectionally **z-score it across the held
  `names`**, and tilt `w_i *= exp(-crowding_tilt_k * z_i)` (high basis → z>0 → down-weight; backwardation →
  z<0 → up-weight), then **renormalize** `w` to sum to 1. A coin with NaN crowding (no perp / pre-launch /
  warmup) → tilt 1.0 (neutral). `crowding_field=None` ⇒ byte-identical to today (beta_null + tsmom recipes
  unaffected). Injectable `_crowding_panel` seam for tests.
- **`basis_tilt` recipe:** `beta_null`'s book + `crowding_field="$basis"`, `crowding_tilt_k=1.0`. Everything
  else frozen, so the A/B isolates the weighting tilt.

## Validation

`zcrypto stress --recipe basis_tilt --null beta_null` → per-window + across-window delta-vs-null with the
paired bootstrap CI + the CPCV distribution. Read cost-adjusted, not gross.

## Success / kill

- **Win:** mean delta-vs-null > 0, CI clears 0 → cross-sectional crowding predicts relative returns; the
  first Stage-2 improvement. Next: tune `k`, add funding/OI to the crowding score, longer/shorter signal.
- **Null/negative:** the tilt doesn't beat `beta_null` → cross-sectional basis-crowding adds no edge over
  inverse-vol. A valid finding; record it. Per `T0023`, OI-price divergence is the next derivatives probe;
  if it also fails, the "shelve derivatives-positioning" call is parked for the human (not the loop).

## Testing (TDD)

- **crowding-tilt unit** (inject `_crowding_panel` + `_vol_panel`): a held basket where one coin has high
  prior basis (z>0) → its weight is reduced vs inverse-vol, a low/negative-basis coin's weight raised, and
  the tilted weights still sum to 1; `crowding_field=None` → byte-identical to today; a NaN-basis coin →
  neutral (tilt 1.0). No look-ahead: the tilt at t uses only rows strictly before t.
- **`basis_tilt` drift-guard** — `beta_null`'s frozen params + `crowding_field="$basis"` + `crowding_tilt_k`;
  the ONLY strategy-kwargs delta vs `beta_null` is the crowding set.
- **stress A/B** — redis-gated: `stress --recipe basis_tilt --null beta_null` writes the delta keys.

## Closeout

`docs/iterations-history.md` iter-40 entry with the measured delta-vs-null verdict; update `T0023`; if
negative, name the next derivatives probe (OI-price divergence).
