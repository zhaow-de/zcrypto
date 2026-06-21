---
status: open
---

# Time-series trend-following + vol-targeting core (and the passive-beta null)

## Context — what

Phase 1 (iters 9–33, see `T0018`) established that daily-OHLCV cross-sectional ML ranking has no
OOS edge and is net-harmful versus simply holding the basket; the only survivor was a defensive
BTC-trend regime gate on an inverse-vol majors basket (`regime_volweight_majors`, across-window
mean OOS Sharpe ~0.50, worst −0.16, selection-bias-inflated). The Phase 2 orientation
([`docs/research/03.phase2-orientation.md`](../research/03.phase2-orientation.md)) reframes that
survivor as **beta-timing, not alpha**, and notes it sits *below* the ~1.0–1.6 net Sharpe that
simple trend-following on crypto majors earns across regimes in the literature (Grayscale MA
study; Moskowitz-Ooi-Pedersen time-series momentum; crypto trend-following studies). This topic
covers the Phase 2 **core** candidate — **per-asset time-series momentum / trend-following with
volatility-targeting**, long/cash on spot — and the **passive-beta null** that every Phase 2
idea must beat.

## Why this matters

Time-series momentum is the most-replicated systematic premium across asset classes, and
volatility-targeting reliably lifts risk-asset Sharpe and cuts left-tail severity — directly
addressing Phase 1's 2025 failure mode (exposure auto-scales down as realized vol spikes in a
crash). It is low-overfitting-risk and low-engineering-cost on the existing pipeline, and is the
most likely honest **core** for the project. Critically, it also defines the **null benchmark**:
until a strategy beats a single naive 200d-SMA-gated inverse-vol majors basket *net of costs*,
the project has demonstrated no edge beyond beta-timing, and that null must be the yardstick for
the whole phase.

## Findings so far

- None yet (Phase 2). Phase 1 priors that bound this work: the *binary* slow gate beats faster
  gates (whipsaw) and graded gates (which stay long through crashes) — iters 23/24; inverse-vol
  weighting holds the mean and roughly halves the worst tail (iter-32); concentration into
  mega-caps is monotonic on the one 2025 holdout but flagged as a bear-market artifact (iter-31,
  do **not** grid-search universe size to the holdout).
- The existing `RegimeGatedTopkStrategy` / `VolWeightedRegimeStrategy`
  (`cli/experiment/strategies/regime.py`) and the `zcrypto stress` OOS harness already supply
  most of the machinery; this is largely a new-recipe + new-signal effort, not new plumbing.

## Suggested next steps

- **Build the passive-beta null first (Stage 0):** 200d-SMA-gated, inverse-vol-weighted basket
  of the 10 majors; compute net-of-cost Sharpe under CPCV + stationary-bootstrap CIs (see the
  validation upgrade in `T0021`/the orientation §5). Record it once; benchmark every later recipe
  against it *inside the same harness*.
- **Per-asset TSMOM signal** at 4h/1d: a standard time-series-momentum / moving-average /
  channel-breakout signal computed per instrument (not cross-sectional), sized to an ex-ante
  volatility target; long/cash (no shorting on spot). New recipe(s) via the existing seam.
- **Volatility-targeting as a return-enhancer**, fed by an intraday realized-vol estimator where
  available; A/B daily-range vol vs intraday realized vol for sizing.
- **Success bar:** net Sharpe ≥ ~1.0 surviving the bootstrap CI *and* beating the Stage-0 null.
  **Kill:** if TSMOM+vol-target cannot beat the null, the honest deliverable is "this is
  beta-timing — ship the simple rule or stop"; if it clears ~1.0 and beats the null, it becomes
  the core and the deep-learning / pairs buckets are shelved.
- Charge realistic costs throughout (iter-19 calibrated model); TSMOM turnover is low, so the
  maker-fill haircut should be modest.
