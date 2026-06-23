---
status: open
---

# `momentum_tilt` candidate — reserved-holdout confirmation (the project's first edge)

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
- **Standing caveats:** deflated Sharpe `nan` (the in-sample multiple-testing adjustment is uncomputable from a
  single-trial register — which is *why* the reserved holdout matters); per-window daily-delta bootstrap CIs
  mostly straddle 0; the magnitude leans on 2024 (though positive in all windows); ~8 overlays were tried
  before momentum (false-discovery context the holdout is designed to defeat).

## Suggested next steps

- **DECISIVE (human-ratified, PARKED — not autonomous):** ratify spending the **reserved-holdout look** on
  `momentum_tilt` (30d, the representative lookback) — the one-shot, un-peeked confirmation. Pre-register the
  trial budget / the exact recipe before peeking. This is the step the loop must not take.
- **Optional reversible pre-checks the loop CAN still run** (each adds in-sample trials, so lower-priority than
  the holdout): a `momentum_tilt_k` strength dose-response (does the edge scale sensibly with tilt strength?);
  sub-period stability beyond the walk-forward windows; `momentum × universe-size` (top-5/top-15) and
  `momentum × vol-target` interactions.
- **If the holdout confirms:** promote `momentum_tilt` to a deployable recipe and hand to the
  live-trading-prep open-topics; if it fails, record that the in-sample +0.200 did not survive the un-peeked
  holdout (multiple-testing / overfitting) and the passive-beta null stands.
