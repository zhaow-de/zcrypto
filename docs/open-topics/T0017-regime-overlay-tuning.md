---
status: open
priority: medium
---

# Regime-overlay tuning (the slow gate works — now refine it)

## Context — what

iter-23 (spec/plan `00022`) discovered that the BTC-trend regime overlay had been **inert since iter-12** (qlib's `TopkDropoutStrategy` sizes buys with the raw `self.risk_degree`, bypassing the overridden `get_risk_degree()`; fixed by a strategy-level workaround). Once actually wired, the **slow binary-200d gate (`regime_steady`) is the project's first OOS-robust improvement**: across-window long-only mean Sharpe **0.289 vs `steady` 0.154**, worst window **−0.220 vs −0.753** (full cash through the 2022 crash; 2025 bear loss halved). Crucially, **faster gates were worse** — `regime_fast` (100d) and `regime_cross` (50/200) *whipsawed*, re-entering on bear-market dead-cat bounces (regime_fast made 2022 −1.28). This topic tracks refining the (now-working) overlay.

## Why this matters

The slow gate is a genuine defensive edge (capital preservation in bears) and the first thing in the project that improves risk-adjusted return out-of-sample across windows. It is defensive, not new alpha — but it is a usable building block, and the whipsaw finding points at concrete levers to push the improvement further (or to combine the gate with a market-neutral book that *does* carry alpha).

## Findings so far

- iter-23: slow binary-200d gate Pareto-beats `steady` (mean 0.289 vs 0.154; worst −0.220 vs −0.753). Faster/cross gates whipsaw and underperform. See the iter-23 entry in `docs/iterations-history.md`.
- The inert-gate root cause + the strategy workaround are in `cli/experiment/strategies/regime.py`; the qlib bug is drafted at `.tmp/qlib-bug-topkdropout-ignores-get-risk-degree.md` (gitignored).

## Suggested next steps

- **Anti-whipsaw gate:** the faster gates churned on bear bounces. Try a confirmation filter (require N consecutive days below the SMA before going to cash / above before re-entering), or a hysteresis band, to get responsiveness without whipsaw.
- **Graded + vol-target modes:** `RegimeGatedTopkStrategy` already supports `graded` (scaled exposure in a chop band) and `vol_target` — A/B these vs the slow binary gate (deferred from iter-23 to keep it small).
- **Apply the slow gate more broadly:** gate other recipes (`funding_steady`, `crossasset_steady`) and — most promising — combine the regime gate with a market-neutral / L/S book, which carries alpha the long-only book lacks.
- **Submit the qlib bug upstream:** file `.tmp/qlib-bug-topkdropout-ignores-get-risk-degree.md` to microsoft/qlib (TopkDropoutStrategy should size buys via `get_risk_degree()`), so the workaround can eventually be retired.
