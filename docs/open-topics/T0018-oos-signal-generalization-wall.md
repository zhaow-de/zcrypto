---
status: open
priority: high
---

# OOS signal-generalization wall (daily-OHLCV alpha doesn't survive 2025+)

## Context — what

Across iters 9–27 the project has established that the cross-sectional alpha learned from **daily OHLCV** (Alpha158/360, cross-asset, funding) is strongly positive in CPCV (~+1.0) on 2020–2024 but **inverts / fails out-of-sample** on the 2025+ holdout, across every window the `zcrypto stress` harness tests. The failure has now been isolated to the **signal**, not the surrounding choices:

- **Feature axis ruled out** (iter-20/25/26): funding and cross-asset features add nothing that survives OOS once regime-gated (funding harmful, cross-asset flat); richer features don't help.
- **Model axis ruled out** (iter-27): a heavily-regularized linear model (Ridge) inverts on 2025 just like LGBM — so it is not an overfitting artifact a simpler model fixes.
- **The one robust edge is defensive:** the BTC-trend regime gate (`regime_voltarget`, iter-24) lifts the OOS mean Sharpe to ~0.31 by sitting out bear regimes — capital preservation, not new alpha.

## Why this matters

This is the central wall blocking profitability. Everything derivable from daily OHLCV has been tried (more features, a different/simpler model) and none generalizes to 2025+. Continuing to permute OHLCV-derived features/models is now low-EV. The decision is: pursue genuinely **new information**, or accept the defensive ceiling.

## Findings so far

- iter-9: `steady` CPCV(+1.0) → holdout(−0.6) inversion, PBO ~0.9.
- iter-22: market-neutral L/S alpha also fails OOS.
- iter-24: regime gate (`regime_voltarget`) is the defensive ceiling (~0.31 OOS mean Sharpe).
- iter-25/26: feature-stacking (funding, cross-asset) redundant/harmful once gated.
- iter-27: linear (Ridge) ≈ LGBM OOS — overfitting refuted; the failure is the signal. The `_fit_predict` model-dispatch seam (`multiseed.py`) now lets any sklearn-style model be tested OOS cheaply.
- See `docs/iterations-history.md` (iters 22–27) for the data.

## Suggested next steps

- **New information (the prime frontier):** on-chain and order-book streams (`T0010` remainder) — the only untried *different* data. A heavier data-acquisition iteration, but the one lever with a real chance of an OOS-surviving edge.
- **Different model classes via the new seam** (low-EV but cheap): ElasticNet, a shallow MLP — but iter-27's refutation makes a generalization breakthrough from model choice unlikely.
- **Accept the defensive ceiling:** treat `regime_voltarget` (~0.31) as the deliverable and shift focus (e.g. live-readiness — out of scope for the research loop).
- **Re-examine the 2025+ regime itself:** is the inversion a one-off bear-market artifact that would revert in a future bull? A longer/rolling holdout as more data accrues would tell.
