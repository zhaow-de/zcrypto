---
status: resolved
---

# Prediction-ensemble (seed-averaged signal)

> **Resolved (irrelevant now):** seed-ensembling was a variance-reduction / production-stability lever for a *selected* ML signal, but iter-27/29/33 (T0018) showed the ML cross-sectional selection is net-harmful OOS — gated no-selection equal-weight beats it — and the deployable strategy is no-ML (gated inverse-vol majors basket). Averaging N copies of a negative-OOS signal cannot rescue it, and there is no production ML recipe to ensemble.

## Context — what

Averaging the predictions of N seed-trained models into one signal — a bagging-over-seeds ensemble — is distinct from iter-14's multi-seed **distribution**. The distribution *measures* the run-to-run variance (report mean ± std over N independent holdout runs); the ensemble *reduces* it (average the N models' per-date scores into a single, lower-variance signal that the backtest then trades). The ensemble may also lift the signal modestly (bagging decorrelates the per-model noise), and it makes a production signal effectively reproducible (the average washes out the per-model jitter that open-topic `T0011` is about).

## Why this matters

iter-14 is expected to show the holdout's run-to-run variance is large enough that the cross-asset edge sits inside the seed-noise band — i.e. no single model is trustworthy. Seed-ensembling is the natural production answer: instead of betting on one (noisy) model, trade the average of N, shrinking the variance by ~1/√N and possibly improving after-cost Sharpe. It is also the bridge from "the comparison is now honest" (iter-14) to "the deployed signal is stable" — a candidate lever for both stability and a marginal edge once a recipe is selected for live use.

## Findings so far

iter-14 builds the multi-seed infrastructure (N seed-fits of the holdout + aggregation). The **same** N models can be ensembled — average their predictions per (date, instrument) — rather than only distributed; the CPCV/holdout would then run once on the ensembled signal. So the ensemble is a small additive step on top of iter-14's machinery, not a separate build. Open question: whether the ensemble's after-cost holdout lands near or above the per-seed mean with materially lower variance, and whether the lift justifies the N× train cost in production.

## Suggested next steps

- Average the N seed-models' predictions into one signal (mean of per-model scores per date/instrument); run the holdout (and optionally CPCV) on the ensembled signal.
- Compare the ensemble's after-cost holdout (Sharpe, PSR, max-DD) against the per-seed distribution from iter-14 — does it land at/above the mean with lower variance?
- Decide whether seed-ensembling is worth the N× training cost as a production-time default for the selected recipe (vs a single deterministic fit).
- Consider richer ensembling (different feature handlers / label horizons, not just seeds) only if seed-ensembling shows a real lift.
