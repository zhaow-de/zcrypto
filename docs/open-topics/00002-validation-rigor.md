---
status: open
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

## Suggested next steps

- Add purged k-fold CV with an embargo sized to label-horizon + feature-lookback.
- Prefer combinatorial purged CV (CPCV) where compute allows.
- Apply the deflated Sharpe ratio when ranking recipes.
- Consider Hudson & Thames MLFinLab for reference implementations.
