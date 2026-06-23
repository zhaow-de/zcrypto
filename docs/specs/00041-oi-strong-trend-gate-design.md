# iter-44 — Stage-2: strong-trend-gated directional OI-divergence tilt (`oi_div_strong_trend`) (design)

**Goal:** capture the one positive derivatives effect — OI-confirmation helps in strong bulls — by applying
the directional OI-divergence tilt **only when the market is in a strong uptrend** (BTC well above its 200d
SMA), neutralizing it elsewhere. **Success bar:** mean delta-vs-null > 0 with bootstrap CI clearing 0, and a
clear improvement over iter-42's +0.010. Decisions `.tmp/decisions.md` iter-044; `T0023`.

## Context

OI-confirmation (iter-41/42) consistently helps 2024 (+0.31/+0.41) but is flat/negative in 2023/2025 — a
strong-bull-regime effect. iter-42 rejected *binary-200d* regime-conditioning (BTC was above its 200d in
both 2023 and 2024, so a binary gate doesn't separate, and gate-state conditioning is a no-op). This uses a
**magnitude** gate: BTC's percent above its 200d SMA. 2024 BTC was ~40–70% above (strong → tilt on); 2025's
downturn keeps BTC near/below (tilt off → removes the −0.178 drag); 2023 partial. **Overfitting guard:** with
only 4 OOS windows, a gate tuned to "2024-good/2025-bad" is a real risk — but the CPCV distribution, the
true-cumulative deflated Sharpe, and the paired bootstrap CI are exactly the guards (a 2024-window-fit signal
shows a straddling CI / low deflated Sharpe). Read those, not the point estimate.

## Design — one gate vs iter-42's directional tilt

Build on `oi_divergence_directional` (iter-42). Add a magnitude regime gate that switches the tilt on/off.

- **Strategy (`VolWeightedRegimeStrategy`):** add `oi_div_strong_trend_only: bool = False` (off →
  unchanged), `oi_div_strong_trend_margin: float = 0.25`. A lazy `_build_strong_trend_signal()`: for the
  `regime_benchmark` (BTC), `pct_above = $close / $close.rolling(regime_ma_window).mean() − 1` (a date-indexed
  series; uses only closes ≤ d via the rolling mean). In `generate_target_weight_position`, inside the OI-div
  tilt block: if `oi_div_strong_trend_only`, look up the **strictly-prior** `pct_above` at the trade date
  (carry-forward ≤ t, same discipline as `_exposure`); if it is NOT `> oi_div_strong_trend_margin` (or is
  NaN/warmup), **skip the tilt entirely** (return the plain inverse-vol weights for that date). Otherwise apply
  the directional OI tilt as in iter-42. Injectable `_strong_trend_signal` seam. `oi_div_strong_trend_only=False`
  ⇒ byte-identical to iter-42. No look-ahead: rolling mean + strictly-prior lookup.
- **`oi_div_strong_trend` recipe:** `oi_divergence_directional`'s kwargs + `oi_div_strong_trend_only=True`,
  `oi_div_strong_trend_margin=0.25`. (i.e. `beta_null` + `oi_divergence=True`, `oi_div_directional=True`,
  `oi_div_lookback=14`, `oi_div_tilt_k=1.0`, `oi_div_strong_trend_only=True`, `oi_div_strong_trend_margin=0.25`.)

## Validation

`zcrypto stress --recipe oi_div_strong_trend --null beta_null` → per-window + across-window delta-vs-null with
the paired bootstrap CI + the CPCV distribution + the deflated Sharpe. Compare to iter-42's +0.010 and to `beta_null`.

## Success / kill

- **Win:** mean delta > 0, CI clears 0, deflated Sharpe survives → OI-confirmation IS a real edge once gated to
  strong trends; next confirm robustness (vary margin; check the CPCV spread).
- **Null / 2024-only / CI straddles:** the gate is just fitting the 2024 window — OI-confirmation is not a
  robust edge. Record it; then derivatives-positioning is thoroughly probed (basis ×2, OI ×3, L/S — all
  ~tapped) and the "shelve derivatives → BTC→alt lead-lag (`T0020`)" call is **well-evidenced, parked for the human**.

## Testing (TDD)

- **strong-trend gate unit** (inject `_strong_trend_signal` + `_oi_div_signal` + `_vol_panel`): on a date where
  prior `pct_above > margin` → the OI tilt is applied (up-mover up-weighted); on a date where `pct_above ≤
  margin` (or NaN) → NO tilt (weights == plain inverse-vol); no look-ahead (strictly-prior).
- **signal unit:** `_build_strong_trend_signal` = BTC `$close / SMA(window) − 1`, causal.
- **back-compat:** `oi_div_strong_trend_only=False` ⇒ byte-identical to iter-42; the other tilts untouched.
- **drift-guard:** `oi_div_strong_trend` = `beta_null` + exactly the six oi-div kwargs.
- **stress A/B** — redis-gated.

## Closeout

`docs/iterations-history.md` iter-44 entry with the delta-vs-null verdict (read the deflated Sharpe + CI, not
just the mean); update `T0023`; if it doesn't clear the bar, record derivatives-positioning as tapped and
restate the parked shelve/pivot call.
