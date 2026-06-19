---
status: resolved
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

**Empirical motivation (PR #41, recipe `steady`).** A recipe-only attempt at a
better risk-adjusted strategy — `steady` (5-day label, low-turnover book
`topk=10`/`hold_thresh=5`, stronger regularization) — was built and validated
against `skeleton` on current data. It did **not** beat `skeleton`: both lose
~63–66% over the 2025–2026 holdout, and `steady` was marginally *worse* on
holdout Sharpe / PSR / excess-vs-BTC. The diagnostic is exactly this topic's
concern — both recipes show a *positive* CPCV out-of-sample Sharpe on 2020–2024
(~+1.0) that **inverts to negative** (~−0.63) on the untouched 2025–2026 holdout,
with PBO = 0.91. That regime shift is the left-tail driver no cross-sectional,
recipe-only tweak corrects; the regime overlay is the lever, not more tuning.

**Scaffold caveat (correction to the note above).** "Ship as a new recipe with
no scaffolding change" is optimistic for the *current* scaffold: `scaffold.py`
hardcodes the `TopkDropoutStrategy` class, and a recipe controls only its kwargs
(`topk`/`n_drop`/`hold_thresh`). A regime-gated strategy therefore needs either
making the strategy class recipe-selectable (a small `scaffold.py` change) or a
TopkDropout-compatible exposure gate — not purely a recipe.

## Suggested next steps

- Add a BTC-trend regime feature (e.g. price vs a long MA / trend slope).
- Gate exposure (full / reduced / cash) off it; optionally vol-target sizing.
- Implement as a new strategy in a recipe; compare to the baseline on the same
  window.

## Resolution

Shipped in iter-12 (spec `00011`, PR targeting `develop`). `RegimeGatedTopkStrategy`
subclasses `TopkDropoutStrategy` and gates gross exposure via qlib's native
`get_risk_degree(trade_step)` hook. Three modes are recipe-tunable: `binary`
(price vs SMA, default 200-day), `graded` (±band around SMA with a `chop_exposure`
middle tier), and `cross` (dual-SMA crossover). A vol-targeting knob (default off)
scales exposure by `min(1, vol_target / realized_vol)`. Demo recipe `regime_steady`
pairs steady's model+book with binary-200d regime and walk-forward holdout retraining.
