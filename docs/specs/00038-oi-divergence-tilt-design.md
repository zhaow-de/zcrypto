# iter-41 — Stage-2: OI-price-divergence cross-sectional tilt (`oi_divergence`) (design)

**Goal:** test whether **OI-price divergence** — "a rally on falling open interest is weak; price + OI
rising together is confirmed" — predicts cross-sectional relative returns, as a weighting tilt on
`beta_null`. **Success bar:** positive mean delta-vs-null whose bootstrap CI clears 0. The last cheap
derivatives probe (`T0023`) after `$basis` was exhausted in both forms (iter-39 timing −0.208, iter-40
cross-sectional tilt −0.183). Decisions `.tmp/decisions.md` iter-041.

## Context

`$basis` failed as both a market-timing gate (iter-39) and a cross-sectional crowding tilt (iter-40). OI
is a **different field and mechanism**: not a price/leverage *level*, but whether open interest is
**confirming the price move** (new money entering) or not (a rally on falling OI = short-covering / no
conviction = weak). The orientation (§3 #2) names OI-price divergence as a distinct derivatives-positioning
edge. This reuses the iter-40 cross-sectional tilt machinery (exp-tilt + renormalize, strictly-prior, no
look-ahead), with a *different signal* and the *opposite* tilt sign (up-weight confirmed, not down-weight).

## Design — one variable vs `beta_null`

Keep `beta_null`'s book verbatim; **add** an OI-divergence confirmation tilt in
`VolWeightedRegimeStrategy.generate_target_weight_position`, applied to the inverse-vol weights.

- **Signal (`_build_oi_div_signal`):** read `$close` and `$oi` panels (`weight_universe`, wide
  date×instrument). Per coin, over a lookback `L` ending strictly before t: `price_chg = close[t-1]/close[t-1-L] − 1`,
  `oi_chg = oi[t-1]/oi[t-1-L] − 1`; **confirmation = sign(price_chg) · oi_chg** (price↑+OI↑ or price↓+OI↓ →
  +confirmed; price↑+OI↓ → −divergent/weak). A date×instrument panel of confirmation scores. NaN where `$oi`
  is NaN (no perp / pre-launch / warmup).
- **Strategy params:** `oi_divergence: bool = False` (off → back-compatible), `oi_div_lookback: int = 14`,
  `oi_div_tilt_k: float = 1.0`. In `generate_target_weight_position`, after `w = inverse_vol_weights(vols)`:
  take the **strictly-prior** confirmation row (same no-look-ahead discipline as the vol/crowding lookups),
  cross-sectionally z-score it across the held `names`, and tilt `w_i *= exp(+oi_div_tilt_k · z_i)` (UP-weight
  confirmed-trend coins — note the **+** sign, opposite the iter-40 crowding tilt), renormalize `w` to sum 1.
  NaN confirmation → tilt 1.0 (neutral); std==0 / <2 names → no tilt. `oi_divergence=False` ⇒ byte-identical
  to today. Injectable `_oi_div_signal` seam for tests. (Reuse/share the iter-40 tilt-application helper if clean.)
- **`oi_divergence_tilt` recipe:** `beta_null`'s book + `oi_divergence=True`, `oi_div_lookback=14`,
  `oi_div_tilt_k=1.0`. Everything else frozen, so the A/B isolates the OI-divergence weighting.

## Validation

`zcrypto stress --recipe oi_divergence_tilt --null beta_null` → per-window + across-window delta-vs-null with
the paired bootstrap CI + the CPCV distribution. Read cost-adjusted, not gross.

## Success / kill

- **Win:** mean delta-vs-null > 0, CI clears 0 → OI-confirmation predicts relative returns; the first Stage-2
  improvement. Next: tune `L`/`k`, combine with price-momentum, try the per-coin filter form.
- **Null/negative:** OI-divergence adds no edge over inverse-vol. **Then all three cheap derivatives probes
  (basis-timing, basis-tilt, OI-divergence) have failed** — the "shelve derivatives-positioning as a dead
  Channel-A sub-bet and redirect to BTC→alt lead-lag (`T0020`)" call (high-stakes) is then **fully
  evidenced**, recorded as **parked for an attended session** (not auto-ratified by the loop).

## Testing (TDD)

- **OI-divergence-tilt unit** (inject `_oi_div_signal` + `_vol_panel`): a held basket where one coin has high
  prior confirmation (price↑+OI↑, z>0) → its weight is RAISED vs inverse-vol, a divergent coin (price↑+OI↓,
  z<0) LOWERED, weights still sum to 1; `oi_divergence=False` → byte-identical; NaN confirmation → neutral; no
  look-ahead (tilt at t uses only rows strictly before t). A signal-construction unit: confirmation =
  sign(price_chg)·oi_chg has the right sign for the four price/OI quadrants.
- **`oi_divergence_tilt` drift-guard** — `beta_null`'s frozen params + the three oi-div kwargs only.
- **stress A/B** — redis-gated: `stress --recipe oi_divergence_tilt --null beta_null` writes the delta keys.

## Closeout

`docs/iterations-history.md` iter-41 entry with the measured delta-vs-null verdict; update `T0023`; if
negative, record that all three cheap derivatives probes failed and restate the parked shelve/pivot call.
