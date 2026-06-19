---
status: open
priority: medium
---

# Multi-window training-stress harness

## Context — what

The current recipes are trained from a fixed start (2020-01-01 by default). A
training-stress harness re-runs a recipe across multiple training-window choices
— e.g. starting in 2017 (pre-bull-run history) vs 2020 (post-crash, higher
quality) — and through named crisis windows (LUNA/FTX 2022, COVID 2020), then
aggregates robustness metrics across all windows. Research §13 Stage 3 names
this as the current robustness stage's work.

## Why this matters

A strategy that looks robust on one training window can degrade badly on another;
sampling multiple windows exposes that sensitivity before the model touches the
holdout. Today `cli/experiment/stress.py` holds named crisis windows for the
report panel but there is no harness that re-runs the full train→CPCV→holdout
pipeline across window choices and aggregates results. Without this, a recipe's
apparent CPCV robustness may be specific to its training start rather than
intrinsic to the strategy.

## Findings so far

Identified during iter-12 scoping (spec `00011`); deferred to this topic.
`cli/experiment/stress.py` exists but only defines named crisis windows for the
4th report panel — it does not orchestrate multi-window retraining. References:
research §13 Stage 3.

## Suggested next steps

- Define the window grid: training starts (2017-01-01, 2020-01-01) × named
  crisis passes (LUNA/FTX, COVID).
- Build a harness (CLI flag or separate subcommand) that loops the grid, writes
  per-window run bundles, and emits a summary table of Sharpe/drawdown/PSR across
  windows.
- Aggregate robustness: flag recipes whose metrics scatter widely across windows
  vs those that are consistently robust.
- Integrate with `zcrypto rank` or a new `zcrypto stress-rank` subcommand so
  multi-window results flow into the deflated-Sharpe accounting.
