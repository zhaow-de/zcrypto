---
status: partial
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

## Done so far

**OOS test-window walk-forward landed (iter-22, spec/plan `00021`).** The `zcrypto stress
--recipe <r> [--seeds N]` subcommand rolls the train→test split across annual OOS windows
(`cli/stress/windows.build_oos_windows` — expanding train from 2020, leak-safe 8-day purge ≥
the label horizon, windows 2022/2023/2024/2025), reusing the iter-21 multi-seed holdout per
window to report per-window long-only `sharpe` vs market-neutral `ls_sharpe` + `stress_summary.json`.
Its first use refuted the iter-21 L/S edge OOS (`steady` mean `ls_sharpe` −0.10 across windows,
negative in the 2022 crisis + 2024; positive only on the dev-seen 2025) — keeping `T0016` gated.
This is the **test-window** axis (the one that addresses selection-bias); see the iter-22 entry in
`docs/iterations-history.md`.

## Suggested next steps

- **Training-window axis (parked, data-limited):** vary the training START (T0007's original "2017
  vs 2020") — but the dataset starts **2020-01-01** (no pre-2020 data), so this is infeasible until
  earlier history is acquired. Low value vs the test-window axis already shipped.
- **Continuous single-curve walk-forward:** one concatenated OOS equity curve (vs the per-window
  grid) for a single honest realized-OOS number — a possible refinement.
- **Integrate with `zcrypto rank`** so multi-window OOS results flow into the deflated-Sharpe
  accounting.
