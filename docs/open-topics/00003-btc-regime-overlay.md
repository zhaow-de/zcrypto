---
status: open
priority: medium
---

# BTC-trend regime overlay (long/cash gating + volatility targeting)

## Context — what

The skeleton's `TopkDropoutStrategy` (spec `00006`) is always fully invested in
the top-k coins. The roadmap's strategy is long/**cash**: scale gross exposure
down — toward USDC/cash — in bear and chop regimes, gated by a BTC-trend filter,
with optional volatility targeting.

## Why this matters

Research §5 — a cross-sectional ranker produces *relative* signal; without a
regime overlay it stays fully invested even when the whole market is falling,
which in crypto means large drawdowns (the roadmap expects 15–30% DD; an overlay
is the main lever on the left tail).

## Findings so far

Deferred from the experiment skeleton (spec `00006`). Because the strategy lives
inside the recipe (the moving part), this can ship as a *new recipe* with no
scaffolding change. References: research §5, §13 Stage 3.

## Suggested next steps

- Add a BTC-trend regime feature (e.g. price vs a long MA / trend slope).
- Gate exposure (full / reduced / cash) off it; optionally vol-target sizing.
- Implement as a new strategy in a recipe; compare to the baseline on the same
  window.
