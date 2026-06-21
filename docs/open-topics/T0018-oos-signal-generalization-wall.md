---
status: open
priority: high
---

# OOS signal-generalization wall (daily-OHLCV alpha doesn't survive 2025+)

## Context — what

Across iters 9–27 the project has established that the cross-sectional alpha learned from **daily OHLCV** (Alpha158/360, cross-asset, funding) is strongly positive in CPCV (~+1.0) on 2020–2024 but **inverts / fails out-of-sample** on the 2025+ holdout, across every window the `zcrypto stress` harness tests. The failure has now been isolated to the **signal**, not the surrounding choices:

- **Feature axis ruled out** (iter-20/25/26): funding and cross-asset features add nothing that survives OOS once regime-gated (funding harmful, cross-asset flat); richer features don't help.
- **Model axis ruled out** (iter-27): a heavily-regularized linear model (Ridge) inverts on 2025 just like LGBM — so it is not an overfitting artifact a simpler model fixes.
- **Target axis ruled out** (iter-28): every label horizon (1/5/10/20-day) inverts on 2025 — the failure is horizon-invariant. All three OHLCV-derived axes (inputs, fitter, target) are now closed.
- **The one robust edge is defensive:** the BTC-trend regime gate (`regime_voltarget`, iter-24) lifts the OOS mean Sharpe to ~0.31 by sitting out bear regimes — capital preservation, not new alpha.
- **The ML selection is net-harmful OOS** (iter-29): gated EQUAL-WEIGHT (`regime_equalweight`, hold the whole universe, no selection) beats gated Alpha158 selection — mean 0.382 vs 0.311. The cross-sectional selection has *negative* mean OOS value (it mis-ranks, giving up broad rallies; it only helps the 2025 bear tail).
- **Basket quality is a real lever** (iter-30/31): a curated 10-large-cap-major gated equal-weight basket beats the broad 19-coin one (mean 0.493 vs 0.382); concentration is monotonic on the holdout (top-5 0.594) but that is partly a 2025-bear artifact — **do not grid-search universe size to the holdout** (meta-overfitting); the 10-major cut is the principled robust default.
- **Inverse-vol weighting improves the tail** (iter-32): `regime_volweight_majors` (risk-parity-lite, down-weight volatile names) holds the mean (0.504) but nearly halves the worst window (−0.158 vs equal-weight's −0.444) — a principled, non-overfitting risk-reduction. **The most defensible deployable strategy: "regime-gate a risk-weighted (inverse-vol) basket of the 10 large-cap majors" — no ML** (mean OOS Sharpe ~0.50, worst −0.16).
- **The cheap, safe, non-overfitting OHLCV/regime vein is now fully exhausted** (features, model class, label horizon, selection, basket quality, weighting all explored). The sole remaining EV-positive frontier is **new information — on-chain / order-book data (T0010)**.
- **Multiple-testing caveat on the run's headline (iter-33, READ THIS before trusting any number):** ~18 distinct recipes were measured against the *same* 2025 OOS stress holdout across iters 23-32 (cross-recipe mean-OOS-Sharpe: best 0.594, median 0.210, std 0.173, min −0.113; selection inflation best−median = +0.38; a rough expected-max-of-18 ≈ 0.6, non-independence of the recipes makes the true selection bias potentially worse). So:
  - **The COARSE finding is structural and robust** — the *slow* binary-200d regime-gate family (0.24-0.59) systematically beats ungated recipes (0.04-0.18), while the *fast* gates whipsaw and underperform even ungated (`regime_cross` −0.11, `regime_fast` 0.11; consistent with iter-23/24). The ML cross-sectional selection is net-harmful, and a quality basket + inverse-vol weighting improve the tail. These are ordered, economically-motivated effects, **not** selection noise.
  - **The FINE ranking is selection-biased** — the exact "best" among the top cluster (`regime_equalweight_top5` 0.594, `regime_volweight_majors` 0.504, `regime_equalweight_majors` 0.493, all within ~1 cross-recipe std) is inflated by testing 18 recipes on one holdout; the very top is near what noise alone could produce.
  - **Honest deployable expectation:** the best strategy's *true* OOS Sharpe is **below its measured ~0.50**; expect live/forward performance meaningfully lower. The principled defaults (gate, equal/inverse-vol, quality basket) are economically motivated (mitigating per-recipe overfit), but the *aggregate* selection across 18 trials on one holdout inflates the headline. **Real validation requires a fresh holdout (data beyond 2026-06) or forward paper-trading** — and a rigorous Deflated Sharpe Ratio over the per-trial return series is a worthwhile follow-up.

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
