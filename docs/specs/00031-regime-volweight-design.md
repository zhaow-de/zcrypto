# Vol-weighted (risk-parity-lite) gated basket — Design

**Iteration:** iter-32
**Advances open-topic:** `T0018` — the one remaining EV-positive, non-overfitting OHLCV-side lever.
**Builds on:** iter-23 (`RegimeGatedTopkStrategy` + `regime_exposure_series`), iter-29/30 (gated equal-weight; basket quality matters), iter-31 (the robust default is `regime_equalweight_majors` — 10 majors).

## Context — what

iter-30/31 showed volatile/lower-quality names drag the equal-weight basket (especially in the bear). The principled response — *not* further concentration (which overfits, iter-31) — is to **weight held names by inverse volatility** (risk-parity-lite): down-weight the more volatile names. This is the natural successor to equal-weight on the 10-major robust default.

## Why this matters

It's the last principled, non-overfitting OHLCV-side improvement to the deployable strategy. If inverse-vol weighting beats equal-weight (better risk-adjusted return, especially a better bear tail), it's a real refinement of the best recipe. If not, equal-weight stands and the OHLCV-side work is conclusively done. Either way it's a clean A/B vs the current best.

## Cardinal correctness concern — NO LOOK-AHEAD

The per-name vol used to weight date *t* MUST be computed from closes **strictly before t** (trailing). A look-ahead vol-weight would still differ from equal-weight AND look good — a false positive the runtime sanity-check cannot catch. **The review must verify the date alignment uses only strictly-prior data** (this is the load-bearing review item).

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Pure `inverse_vol_weights(vols: pd.Series) -> pd.Series`** in `cli/experiment/strategies/regime.py`: `w = (1/vols)` over finite, strictly-positive vols, normalized to sum 1; non-finite / ≤0 vols dropped (weight 0) then renormalized; empty → equal-weight fallback. | A small pure function — unit-testable without qlib (the only subtle math). Risk-parity-lite (inverse-vol, no covariances). |
| 2 | **`VolWeightedRegimeStrategy(WeightStrategyBase)`** in `regime.py`: `__init__` takes the regime params (mode/ma_window/vol_target/benchmark — reuse the gate) + `weight_universe` (the recipe's universe, passed explicitly) + `weight_vol_lookback=30`; loads `$close` for `weight_universe` once and builds a **trailing** realized-vol panel (`pct_change().rolling(lookback).std()`); builds the regime exposure (`regime_exposure_series`). `generate_target_weight_position(score, …, trade_start_time, …)` → look up each scored name's vol at the most recent date **strictly < trade_start_time** (carry-forward, NO look-ahead) → `inverse_vol_weights` → return the weight dict. `get_risk_degree` returns `_base_risk_degree * regime_mult` (the gate). | `WeightStrategyBase`'s order generator scales target weights by `get_risk_degree`, so the regime gate composes **natively** (no iter-23 workaround). The inverse-vol weights are the cross-sectional distribution; the gate scales total exposure (timing) — two distinct, principled vol uses. |
| 3 | **Recipe `regime_volweight_majors`** = `regime_equalweight_majors`'s book (10 majors, DummyRegressor constant signal → all majors scored each date) + `VolWeightedRegimeStrategy` with the same gate (binary 200d + vol_target 0.50) + `weight_universe` = the 10 majors + `weight_vol_lookback=30`. | A/B vs `regime_equalweight_majors` isolates inverse-vol vs equal weighting. 10-major (the robust default), not top-5. |
| 4 | **HARD validation:** (a) review verifies no look-ahead (cardinal); (b) the stress result MUST differ from `regime_equalweight_majors` (else a silent bug — cf. iter-23's inert gate); (c) no crash. | The differs-from-equal-weight check catches an inert weighting; the review catches look-ahead (which the runtime cannot). |

## Component file tree

```
cli/experiment/strategies/
└── regime.py    # MODIFY: add inverse_vol_weights(vols) (pure) + VolWeightedRegimeStrategy(WeightStrategyBase)
                 #         (trailing per-name vol panel, strictly-prior lookup; gate via get_risk_degree).
cli/experiment/recipes/
└── regime_volweight_majors.py  # NEW: 10-major book + VolWeightedRegimeStrategy + the gate.
tests/
├── test_regime_strategy.py     # EXTEND: inverse_vol_weights — higher vol -> lower weight; weights sum to 1;
│                              #         non-finite/≤0 dropped+renormalized; empty -> equal-weight.
└── test_experiment_recipe.py   # EXTEND: regime_volweight_majors resolves; strategy is VolWeightedRegimeStrategy
                               #         with the gate kwargs + weight_universe = 10 majors; data book matches steady.
README.md                       # MODIFY: Usage — add regime_volweight_majors.
```

## A/B & verdict

Closeout (redis up): run `zcrypto stress --recipe regime_volweight_majors --seeds 8`; reuse `regime_equalweight_majors`. Per-window long-only Sharpe + mean / worst. **First verify the result is NOT bit-identical to `regime_equalweight_majors`** (else a silent weighting bug → stop + fix). Verdict → `docs/iterations-history.md`: does inverse-vol weighting beat equal-weight (esp. a better bear tail)?

## Scope & deferred

- **In:** the pure `inverse_vol_weights` + `VolWeightedRegimeStrategy` (+ unit tests); `regime_volweight_majors`; the A/B + verdict; README; T0018 note.
- **Out:** full mean-variance/covariance optimization; vol-weighting other baskets; on-chain (T0010).
- **Untouched:** `RegimeGatedTopkStrategy` (reused for the exposure logic), the `_fit_predict` seam, harnesses, data/cost.

## Closeout tasks (authored when the work is real)

- Run `regime_volweight_majors` stress; confirm it differs from equal-weight; A/B vs `regime_equalweight_majors` → record the inverse-vol verdict + running best.
- iter-32 iterations-history entry; update `T0018`; README.
- At the 09:00 gate: comprehensive hand-back (best strategy + the wall + on-chain as the remaining new-info frontier).
