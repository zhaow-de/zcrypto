# Model-dispatch holdout + linear model OOS test — Design

**Iteration:** iter-27
**Pivots off:** the feature-stacking thread (closed iter-25/26 — no feature add beats the gate). New frontier: the **model axis**.
**Builds on:** iter-14 (multi-seed holdout), iter-22/24 (`zcrypto stress`, `regime_voltarget` = best recipe), the iter-9 finding that `steady`'s CPCV(+1.0) inverts to holdout(−0.6).

## Context — what

Every result so far uses LGBM on Alpha158. The CPCV(+1.0) → holdout(−0.6) inversion looks like **LGBM overfitting the 2020-2023 training regime**. This iteration tests the hypothesis directly: does a heavily-regularized **linear model** (sklearn `Ridge`) on the *same* Alpha158 features generalize OOS better (or at least not invert as hard)?

Blocker: the multi-seed holdout (`multiseed._light_holdout`) **hardcodes `lgb.train`** — it cannot run any other model. So step one is to make the fit/predict step model-dispatched, *without changing the LGBM path's behavior at all* (every existing recipe must produce identical results).

## Why this matters

If a simpler model generalizes where LGBM inverts, that reframes the whole project (overfitting, not signal absence, is the OOS problem) and gives a better base book to gate. If linear is no better, that's also decisive — the OOS failure is the *signal*, not model complexity — and we stop blaming the model. Either way, the **model-dispatch seam is reusable infrastructure** that unlocks testing any sklearn-style model (linear, ElasticNet, etc.) on the OOS harness — the natural successor to the (now-closed) feature axis.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Extract a pure `_fit_predict(recipe, x_tr, y_tr, x_pe, *, seed, deterministic) -> np.ndarray`** in `multiseed.py`. **LGBM branch** (`model_config["class"] == "LGBModel"`) = the EXISTING code verbatim (`_lgb_params(recipe, seed, deterministic)` + `lgb.train` + `booster.predict`). **Else branch** = `importlib` the class from `model_config["module_path"]`, instantiate with `kwargs`, `model.fit(x_tr.values, y_tr.values)`, `model.predict(x_pe.values)`. `_light_holdout` calls it for the signal; everything else (the backtest) unchanged. | The LGBM path stays byte-identical (it's literally the same lines, just moved into a branch) → zero behavior change for existing recipes. The else branch supports any sklearn-style regressor with `.fit`/`.predict` on matrices. Pure (matrices in → predictions out) so it's unit-testable without qlib/redis. |
| 2 | **New recipe `linear_steady`** = `steady`'s book verbatim + `model_config = {"class": "Ridge", "module_path": "sklearn.linear_model", "kwargs": {"alpha": 10.0}}`. | Tests the simplest regularized linear model on Alpha158. `alpha=10.0` is a moderate-strong ridge penalty for ~158 standardized features (a reasonable first pass; tunable later). `Ridge` is deterministic → the multi-seed distribution is a (correct) point; `summarize_seed_metrics` handles `std=0`. |
| 3 | **Regression safety gate (cardinal):** after the refactor, `steady`'s stress result MUST be unchanged (mean OOS Sharpe 0.154). The closeout re-runs `steady` and compares; any drift means the LGBM branch was altered → fix before merge. | The change touches the core measurement path; the only acceptable outcome for LGBM recipes is identical numbers. |
| 4 | **A/B (closeout):** `steady` (LGBM) vs `linear_steady` (Ridge), ungated; and — if linear looks promising — gated (`regime_voltarget` vs a gated-linear). Read cost-adjusted Sharpe (`T0015`). | Tests the overfitting hypothesis (does Ridge avoid the inversion?) and whether a linear base book, gated, beats `regime_voltarget` (0.311). |

## Component file tree

```
cli/experiment/
└── multiseed.py    # MODIFY: extract _fit_predict(recipe, x_tr, y_tr, x_pe, *, seed, deterministic) -> np.ndarray
                    #         (LGBM branch verbatim; else = importlib + fit/predict on matrices). _light_holdout
                    #         calls it for `signal`; the lightgbm import moves into the LGBM branch.
cli/experiment/recipes/
└── linear_steady.py  # NEW: steady's book + model_config Ridge(alpha=10.0).
tests/
├── test_multiseed.py          # EXTEND: _fit_predict pure-matrix tests — an LGBModel recipe returns len(x_pe)
│                              #         predictions; a Ridge recipe returns len(x_pe) predictions; (optional) the
│                              #         LGBM branch is taken for LGBModel.
└── test_experiment_recipe.py  # EXTEND: linear_steady resolves; model_config is Ridge/sklearn.linear_model/alpha=10.0;
                               #         book (handler/label/segments/universe/fees/feature_config) matches steady.
README.md                      # MODIFY: Usage — add linear_steady.
```

## A/B & verdict

Closeout (redis up): **regression-gate first** — run `zcrypto stress --recipe steady --seeds 8` and confirm mean ≈ 0.154 (LGBM path unchanged). Then run `linear_steady`; assemble `steady` vs `linear_steady` (+ `regime_voltarget` for context). Verdict → `docs/iterations-history.md`:
- Does `linear_steady` avoid the OOS inversion / beat `steady` (LGBM) across windows? → overfitting was the problem; linear is a better base.
- If `linear_steady` is no better → the OOS failure is the signal, not model complexity; the model axis (at least linear) is closed.

## Scope & deferred

- **In:** the `_fit_predict` model-dispatch seam (+ unit tests); `linear_steady`; the regression gate + A/B + verdict; README.
- **Out (future, enabled by the seam):** other models (ElasticNet, qlib neural nets — those need a Dataset wrapper, not matrices); gating the linear book (only if linear looks promising); alpha tuning.
- **Untouched:** the LGBM path's behavior (byte-identical), `_lgb_params`, the strategy/cost/data layers, the stress command.

## Closeout tasks (authored when the work is real)

- **Regression gate:** confirm `steady`'s stress mean is unchanged (≈0.154) after the refactor — STOP and fix if not.
- Run `linear_steady` stress; A/B vs `steady` (+ `regime_voltarget`) → record the overfitting-hypothesis verdict.
- iter-27 iterations-history entry (the seam + the linear verdict); if linear is promising, open a follow-up topic (gate it / tune alpha / try ElasticNet); if not, record the model axis (linear) as closed.
- README `## Usage`: `linear_steady`.
