---
status: open
---

# `momentum_tilt` candidate — downgraded (failed its in-sample significance bar)

> **Correction (2026-06-25).** This topic originally framed `momentum_tilt` as "the project's first
> edge," teed up for a reserved-holdout look. That framing is withdrawn. The +0.200 was promoted past a
> **broken deflated-Sharpe check** (the trial register had lost its history → deflated Sharpe `NaN`; see
> [`T0025`](T0025-trial-register-durability.md)). Assessed properly on the saved paired daily-delta
> bootstraps, momentum's edge over the null pools to **`t ≈ 1.3`** — below the naive `t > 2`, far below
> the pre-registered `t > 3` multiple-testing bar. The reserved-holdout look is **moot**: momentum is not
> a confirmable edge on the data already seen, and the 2025 `test` segment is not pristine anyway (it
> overlaps the `oos_2025` stress window already inside the +0.200). The candidate is **not** a confirmed
> edge; the deployable answer remains `beta_null` / `regime_voltarget` (~0.31 OOS).

## Context — what

`momentum_tilt` (a cross-sectional **price-momentum** tilt on `beta_null`: overweight the held basket's
recent relative winners, trailing 30d return, `w_i *= exp(+k·z_i)`) is the **first overlay to beat the
passive-beta null `beta_null`** out-of-sample (iter-47, +0.200 mean delta, positive in all three active
windows). The reversible robustness work has confirmed it on three independent axes — signal direction
(iter-47), **lookback** (iter-48: +0.14–0.21 across 14/30/60/90d), and **cost/turnover** (iter-49: +0.194 at
2× the maker-fill haircut). The **decisive, multiple-testing-proof confirmation is the reserved-holdout look**,
which is a **human-ratified** step (parked — the autonomous loop must not spend the reserved holdout or
pre-register the trial budget). This topic tracks that confirmation and the remaining reversible pre-checks.

## Why this matters

After ~30 Phase-1/2 iterations the standing finding was that **nothing beats passive-beta** — every alpha
overlay (per-asset TSMOM, derivatives basis/OI/L-S, on-chain NVM — ~8 fade-strength/positioning signals)
failed. `momentum_tilt` is the **first exception**, and it is the opposite direction (overweight strength, not
fade it) — consistent with the night's "momentum-dominated regime" finding. If the reserved-holdout look
confirms it, the project has its **first deployable cross-sectional edge** beyond market-beta-timing. The
reserved holdout is the project's **one-shot, un-peeked, multiple-testing-proof** test; spending it is a
deliberate human decision precisely because it can only be spent once — and `momentum_tilt` is the strongest
candidate to date to spend it on.

## Findings so far

- iter-47 (PR #99, spec `00044`): `momentum_tilt` (30d) delta-vs-`beta_null` **+0.200**, per-window
  +0.00/+0.108/+0.529/+0.164 — positive in all 3 active windows.
- iter-48 (PR #100): **lookback-robust** — l14 +0.210, l30 +0.200, l60 +0.146, l90 +0.142 (all positive); the
  per-window source rotates (short→2023+2024, long→2024+2025) but every lookback's mean is positive.
- iter-49 (PR #101): **cost-robust** — +0.194 at 2× the turnover-scaling maker-fill haircut (vs +0.200 at 1×;
  −0.006 erosion). Momentum's extra turnover is modest (re-weights the monthly basket, doesn't re-select).
- iter-50 (PR #102): **clean dose-response** — delta scales monotonically with tilt strength k and plateaus:
  k0.5 +0.107, k1.0 +0.200, k1.5 +0.221, k2.0 +0.223. The signature of a real signal. k1.0 stays the robust
  default (positive in all windows); higher k lifts the mean to ~+0.22 but turns 2023 slightly negative
  (over-concentration). So the candidate is confirmed on **four axes** — direction, lookback, cost, strength.
- **Standing caveats:** deflated Sharpe `nan` (the in-sample multiple-testing adjustment is uncomputable from a
  single-trial register — which is *why* the reserved holdout matters); per-window daily-delta bootstrap CIs
  mostly straddle 0; the magnitude leans on 2024 (though positive in all windows); ~8 overlays were tried
  before momentum (false-discovery context the holdout is designed to defeat).

## Suggested next steps

- **Do NOT spend a reserved-holdout look on the 2025 segment.** It is moot on two independent grounds:
  momentum fails its in-sample significance bar (pooled daily-delta `t≈1.3`), and the 2025 `test` segment
  is not pristine (it overlaps the `oos_2025` stress window already inside the +0.200). A "look" there
  would confirm seen data, not test the candidate.
- **Fix the measurement first** ([`T0025`](T0025-trial-register-durability.md)) — repair the trial register
  / deflated-Sharpe integrity so any future candidate (momentum or otherwise) is judged against a real bar.
- **Only genuine confirmation path:** retest momentum on **out-of-time data the search never saw**
  (forward-walk / paper validation, ties to `T0006`). That is the sole way an in-sample signal like this
  could be confirmed; treat momentum as a low-conviction prior until then.
