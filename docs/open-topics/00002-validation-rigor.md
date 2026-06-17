---
status: partial
priority: high
---

# Validation rigor: purged k-fold CV + embargo, CPCV, deflated Sharpe

## Context — what

The experiment skeleton (spec `00006`) evaluates on a single chronological
train/valid/test split. Its label is a 1–3-day forward return, which overlaps
neighboring rows, so rows near the split boundary leak future information across
it. Separately, the harness exists to compare many `--recipe` runs, which
invites selection bias (best-of-N looks better than it is).

## Why this matters

Research §6/§12 (López de Prado, Ch. 7) names backtest overfitting *the* primary
killer of retail ML strategies — testing 20 variants and picking the best can
turn a true Sharpe < 0.5 into an apparent 2.0. The plain split + uncorrected
comparison will systematically overstate any recipe's edge.

## Findings so far

Opened during the experiment-skeleton design (spec `00006`); the skeleton ships
the simple split deliberately for a first end-to-end run. This topic tracks the
upgrade. References: `docs/research/01.binance-eea-spot-quant.md` §6 (purged
k-fold + embargo), §12 (overfitting), §13 Stage 2–3.

## Done so far

Landed in iter-9 (spec `docs/specs/00008-validation-rigor-cpcv-design.md`):

- Purged k-fold CV with an embargo sized to label-horizon + feature-lookback,
  closing the flagged train/valid/test boundary leakage (`cli/experiment/cv.py`).
- Combinatorial purged CV (CPCV) as the **default** `experiment` run: many
  purged + embargoed splits stitched into multiple backtest paths → a per-recipe
  distribution of out-of-sample Sharpe / return / max-DD (+ rank-IC), with the
  `test` window kept as an untouched final holdout (`cli/experiment/cpcv.py`,
  `cv_results.json`, the 4th report panel). `--quick` keeps the single run.

## Suggested next steps

Still open — deferred from iter-9:

- Apply the deflated Sharpe ratio (and PBO, probability of backtest overfitting)
  on top of the CPCV path distribution.
- Build the multi-recipe comparison / ranking surface deflated Sharpe needs (it
  must track the number of trials N across recipe runs) — the reason this slice
  was deferred.
- Consider Hudson & Thames MLFinLab for reference implementations.
