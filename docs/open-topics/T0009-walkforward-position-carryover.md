---
status: open
priority: low
---

# Walk-forward position carry-over

## Context — what

The iter-12 walk-forward holdout (`cli/experiment/walkforward.py`) backtests each
retrain period independently: every period starts all-cash and ends by liquidating
all positions. Period boundaries therefore incur a re-entry cost at the start and
skip the prior period's liquidation cost. The current approach is deliberately
conservative and mirrors CPCV's per-path independence, but it introduces an
artificial performance seam at each boundary.

## Why this matters

The all-cash-at-start assumption overstates re-entry friction (every boundary
forces a full portfolio reconstruction) while simultaneously understating exit
friction (the prior period's final positions are silently discarded rather than
sold). For a quarterly retrain cadence these seams occur four times per year;
at higher turnover the boundary cost is material. A continuous backtest that
swaps the model at retrain boundaries — without liquidating — would remove the
artifact and give a more realistic picture of the walk-forward's net P&L.

## Findings so far

Identified during iter-12 implementation (spec `00011`); the conservative
all-cash design was chosen intentionally to keep the first walk-forward
implementation simple and comparable to CPCV path backtests. The limitation
is documented in spec `00011` (Phase B) and this topic. References:
`cli/experiment/walkforward.py` (iter-12), spec `00011`.

## Suggested next steps

- Implement a continuous holdout mode: run one unbroken backtest over the full
  holdout window, swapping the fitted model at each retrain boundary without
  liquidating (qlib `SignalSeriesStrategy` or a custom signal-injection hook).
- Compare the continuous-mode equity curve to the current period-independent
  curve to quantify the boundary-cost artifact.
- Consider exposing both modes as a `wf_boundary` knob (`independent` vs
  `continuous`) on the recipe so recipes can opt in to carry-over.
- Verify that position carry-over is consistent with the fee model (partial
  turnover at each boundary rather than full round-trip).
