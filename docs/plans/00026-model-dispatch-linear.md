# Model-dispatch Holdout + Linear Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the multi-seed holdout model-dispatched (LGBM path byte-identical; any sklearn-style model supported) and add a `linear_steady` recipe, so the iter-27 closeout can A/B whether a regularized linear model generalizes OOS better than LGBM.

**Architecture:** Extract a pure `_fit_predict(recipe, x_tr, y_tr, x_pe, *, seed, deterministic) -> np.ndarray` in `multiseed.py`. The LGBM branch is the existing `_lgb_params` + `lgb.train` + `booster.predict` verbatim; the else branch `importlib`s the model class from `model_config` and calls `.fit`/`.predict` on the raw matrices. `_light_holdout` calls it for the signal; nothing else changes. `linear_steady` is `steady`'s book + a Ridge `model_config`.

**Tech Stack:** Python 3.12, uv, qlib, lightgbm, scikit-learn (Ridge), pytest, ruff.

## Global Constraints

- **The LGBM path must stay byte-identical** — for `model_config["class"] == "LGBModel"`, `_fit_predict` runs exactly the existing lines (`_lgb_params(recipe, seed=seed, deterministic=deterministic)` → `lgb.train(params, lgb.Dataset(x_tr.values, label=y_tr.values), num_boost_round=num_boost_round)` → `booster.predict(x_pe.values)`). No behavior change for any existing recipe. (Regression-gated at closeout: `steady`'s stress mean must remain ≈0.154.)
- **`_fit_predict` is pure:** matrices in (`x_tr`, `y_tr`, `x_pe` are pandas; use `.values`), `np.ndarray` out. No qlib/ctx dependency, so it is unit-testable directly.
- **The else branch** treats `model_config` as an sklearn-style regressor: `cls = getattr(importlib.import_module(model_config["module_path"]), model_config["class"]); model = cls(**model_config.get("kwargs", {})); model.fit(x_tr.values, y_tr.values); return np.asarray(model.predict(x_pe.values))`.
- **`linear_steady`** copies `steady`'s book verbatim, changing ONLY `model_config` to `{"class": "Ridge", "module_path": "sklearn.linear_model", "kwargs": {"alpha": 10.0}}`.
- ruff: line length 132, double quotes, import sorting. `uv run ruff check --fix` + `uv run ruff format` before commit.
- Commit: `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: `_fit_predict` model-dispatch seam

**Files:**
- Modify: `cli/experiment/multiseed.py`
- Test: `tests/test_multiseed.py` (extend)

**Interfaces:**
- Produces: `_fit_predict(recipe, x_tr, y_tr, x_pe, *, seed, deterministic) -> np.ndarray` (module-level in `multiseed.py`). Consumed by `_light_holdout`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_multiseed.py`:

```python
def test_fit_predict_lgbm_branch_returns_predictions():
    """LGBM recipe -> the existing lgb path; returns one prediction per holdout row."""
    import numpy as np
    import pandas as pd

    from cli.experiment.multiseed import _fit_predict
    from cli.experiment.recipes.base import resolve_recipe

    rng = np.random.RandomState(0)
    x_tr = pd.DataFrame(rng.rand(60, 6))
    y_tr = pd.Series(rng.rand(60))
    x_pe = pd.DataFrame(rng.rand(9, 6))
    pred = _fit_predict(resolve_recipe("steady"), x_tr, y_tr, x_pe, seed=1, deterministic=True)
    assert len(pred) == 9


def test_fit_predict_generic_sklearn_branch_returns_predictions():
    """A non-LGBM (sklearn-style) model_config -> importlib + fit/predict on matrices."""
    from types import SimpleNamespace

    import numpy as np
    import pandas as pd

    from cli.experiment.multiseed import _fit_predict

    rng = np.random.RandomState(0)
    x_tr = pd.DataFrame(rng.rand(60, 6))
    y_tr = pd.Series(rng.rand(60))
    x_pe = pd.DataFrame(rng.rand(9, 6))
    recipe = SimpleNamespace(
        model_config={"class": "Ridge", "module_path": "sklearn.linear_model", "kwargs": {"alpha": 1.0}}
    )
    pred = _fit_predict(recipe, x_tr, y_tr, x_pe, seed=1, deterministic=True)
    assert len(pred) == 9
    assert np.isfinite(pred).all()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_multiseed.py -k fit_predict -v`
Expected: FAIL — `ImportError: cannot import name '_fit_predict'`.

- [ ] **Step 3: Add `_fit_predict` to `cli/experiment/multiseed.py`**

Add this module-level function (place it just above `_light_holdout`):

```python
def _fit_predict(recipe, x_tr, y_tr, x_pe, *, seed, deterministic):
    """Fit the recipe's model on the train matrices and predict the holdout rows.

    LGBM (``model_config["class"] == "LGBModel"``) uses the existing per-seed bagging-RNG path
    verbatim (the multi-seed determinism contract). Any other model is treated as an sklearn-style
    regressor: imported from ``model_config["module_path"]`` and fit/predicted on the raw matrices
    (deterministic models simply yield identical predictions across seeds).
    """
    import numpy as np

    mc = recipe.model_config
    if mc["class"] == "LGBModel":
        import lightgbm as lgb

        from cli.experiment.cpcv import _lgb_params

        params, num_boost_round = _lgb_params(recipe, seed=seed, deterministic=deterministic)
        booster = lgb.train(params, lgb.Dataset(x_tr.values, label=y_tr.values), num_boost_round=num_boost_round)
        return booster.predict(x_pe.values)

    import importlib

    cls = getattr(importlib.import_module(mc["module_path"]), mc["class"])
    model = cls(**mc.get("kwargs", {}))
    model.fit(x_tr.values, y_tr.values)
    return np.asarray(model.predict(x_pe.values))
```

- [ ] **Step 4: Refactor `_light_holdout` to call `_fit_predict`**

In `_light_holdout`, the current body computes the signal via an inline lgb fit. Replace the import line and the fit block. Specifically:

Change the import line:
```python
    from cli.experiment.cpcv import _lgb_params, _rows_on
```
to:
```python
    from cli.experiment.cpcv import _rows_on
```

And replace these lines:
```python
    params, num_boost_round = _lgb_params(recipe, seed=seed, deterministic=deterministic)

    x_tr = _rows_on(ctx.learn_feat, ctx.train_dates)
    y_tr = _rows_on(ctx.learn_label, ctx.train_dates)
    booster = lgb.train(params, lgb.Dataset(x_tr.values, label=y_tr.values), num_boost_round=num_boost_round)

    x_pe = _rows_on(ctx.infer_feat, ctx.predict_dates)
    signal = pd.Series(booster.predict(x_pe.values), index=x_pe.index).sort_index()
```
with:
```python
    x_tr = _rows_on(ctx.learn_feat, ctx.train_dates)
    y_tr = _rows_on(ctx.learn_label, ctx.train_dates)
    x_pe = _rows_on(ctx.infer_feat, ctx.predict_dates)
    signal = pd.Series(
        _fit_predict(recipe, x_tr, y_tr, x_pe, seed=seed, deterministic=deterministic),
        index=x_pe.index,
    ).sort_index()
```

Also remove the now-unused `import lightgbm as lgb` from `_light_holdout`'s local imports (it moved into `_fit_predict`'s LGBM branch). Keep `import pandas as pd` and the `from qlib.backtest import backtest` / scaffold imports.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_multiseed.py -k fit_predict -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Lint + full multiseed test module + commit**

```bash
uv run ruff check --fix cli/experiment/multiseed.py tests/test_multiseed.py
uv run ruff format cli/experiment/multiseed.py tests/test_multiseed.py
uv run pytest tests/test_multiseed.py -q
git add cli/experiment/multiseed.py tests/test_multiseed.py
git commit -m "refactor(experiment): model-dispatch the holdout fit/predict (_fit_predict seam)"
```

Expected: `tests/test_multiseed.py` passes (the existing tests + the 2 new `_fit_predict` tests). The LGBM path is unchanged, so the existing multiseed tests must still pass.

---

### Task 2: `linear_steady` recipe

**Files:**
- Create: `cli/experiment/recipes/linear_steady.py`
- Modify: `README.md` (Usage recipe list)
- Test: `tests/test_experiment_recipe.py` (extend)

**Interfaces:**
- Consumes: `cli.experiment.recipes.base.Recipe`; the Task 1 `_fit_predict` generic branch (at runtime); `resolve_recipe`.
- Produces: recipe resolvable as `linear_steady`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_recipe.py`:

```python
def test_linear_steady_is_ridge_on_steady_book():
    ln, st = resolve_recipe("linear_steady"), resolve_recipe("steady")
    mc = ln.model_config
    assert mc["class"] == "Ridge"
    assert mc["module_path"] == "sklearn.linear_model"
    assert mc["kwargs"]["alpha"] == 10.0
    # steady's book preserved (only the model differs)
    assert ln.handler_kwargs == st.handler_kwargs
    assert ln.feature_config == st.feature_config
    assert ln.strategy_config == st.strategy_config
    assert ln.universe == st.universe and ln.segments == st.segments
    assert ln.fee_preset == st.fee_preset and ln.label_horizon_days == st.label_horizon_days
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_experiment_recipe.py -k linear_steady -v`
Expected: FAIL — recipe not found.

- [ ] **Step 3: Create `cli/experiment/recipes/linear_steady.py`**

```python
"""linear_steady recipe — steady's book + a regularized LINEAR model (Ridge) instead of LGBM.

iter-27 model-axis test: does a heavily-regularized linear model generalize OOS better than
LGBM? steady's Alpha158 CPCV(+1.0) inverts to a negative holdout, which looks like LGBM
overfitting the training regime. Ridge (alpha=10.0) on the same features is the simplest
regularized alternative. Everything except model_config is steady's book verbatim, so the A/B
isolates the model. Runs via the iter-27 _fit_predict model-dispatch seam (sklearn fit/predict
on the raw matrices); Ridge is deterministic, so the multi-seed distribution is a point.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="linear_steady",
    handler_kwargs={
        "infer_processors": [
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
        "label": (["Ref($close, -6)/Ref($close, -1) - 1"], ["LABEL0"]),
    },
    model_config={
        "class": "Ridge",
        "module_path": "sklearn.linear_model",
        "kwargs": {"alpha": 10.0},
    },
    strategy_config={
        "class": "TopkDropoutStrategy",
        "module_path": "qlib.contrib.strategy.signal_strategy",
        "kwargs": {"topk": 10, "n_drop": 1, "hold_thresh": 5},
    },
    feature_config={"class": "Alpha158", "module_path": "qlib.contrib.data.handler"},
    segments={
        "train": ("2020-01-01", "2023-12-31"),
        "valid": ("2024-01-01", "2024-12-31"),
        "test": ("2025-01-01", "2026-06-15"),
    },
    universe=(
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "AVAXUSDT",
        "LINKUSDT",
        "DOGEUSDT",
        "TRXUSDT",
        "DOTUSDT",
        "POLUSDT",
        "LTCUSDT",
        "ATOMUSDT",
        "UNIUSDT",
        "NEARUSDT",
        "ARBUSDT",
        "APTUSDT",
        "PEPEUSDT",
    ),
    reference_instruments=("BTCEUR", "ETHBTC"),
    account=10_000.0,
    benchmark="BTCUSDT",
    fee_preset="vip2_bnb",
    label_horizon_days=6,
    feature_lookback_days=60,
    cv_n_groups=6,
    cv_test_groups=2,
)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_experiment_recipe.py -k linear_steady -v`
Expected: PASS.

- [ ] **Step 5: Update README Usage**

In `README.md` `## Usage`, find the recipe list and add a row:
- `linear_steady` — steady's book with a regularized linear model (Ridge, alpha=10) instead of LGBM (iter-27 model-axis test).

Match the existing row format. Don't hand-edit the mdformat TOC.

- [ ] **Step 6: Lint + recipe-test run + commit**

```bash
uv run ruff check --fix cli/experiment/recipes/linear_steady.py tests/test_experiment_recipe.py
uv run ruff format cli/experiment/recipes/linear_steady.py tests/test_experiment_recipe.py
uv run pytest tests/test_experiment_recipe.py -q
git add cli/experiment/recipes/linear_steady.py tests/test_experiment_recipe.py README.md
git commit -m "feat(experiment): add linear_steady (Ridge) recipe"
```

Expected: the recipe test module passes.

---

## Closeout (operational — run by the orchestrator after Tasks 1-2 land, NOT a subagent task)

1. **Regression gate FIRST** (redis up): `uv run zcrypto stress --recipe steady --seeds 8` → confirm the mean OOS Sharpe is unchanged (≈0.154, matching the iter-23/24 runs). If it differs, the LGBM path was altered — STOP and fix Task 1 before proceeding.
2. **Run `linear_steady`:** `uv run zcrypto stress --recipe linear_steady --seeds 8`.
3. **Verdict** → `docs/iterations-history.md`: per-window long-only Sharpe for `steady` (LGBM) vs `linear_steady` (Ridge) + `regime_voltarget` for context. Does Ridge avoid the OOS inversion / beat LGBM? → overfitting was the problem. If no better → the OOS failure is the signal, not model complexity.
4. If linear is promising, note a follow-up (gate it / tune alpha / ElasticNet); else record the linear model axis as closed.
5. **README** recipe list (Task 2) — confirm.
6. **iter-27 iterations-history entry** (the `_fit_predict` seam + the linear verdict).

---

## Self-Review

**Spec coverage:** Decision 1 (`_fit_predict` seam, LGBM verbatim + generic) → Task 1; Decision 2 (`linear_steady` Ridge) → Task 2; Decision 3 (regression gate) → Closeout 1; Decision 4 (A/B) → Closeout 2-3. README → Task 2 Step 5; verdict + history → Closeout 3-6.

**Placeholder scan:** No TBD/TODO. Full code in both tasks (the `_fit_predict` function, the `_light_holdout` before/after, the recipe). Verdict values are closeout.

**Type consistency:** `_fit_predict(recipe, x_tr, y_tr, x_pe, *, seed, deterministic) -> np.ndarray` — same signature in Task 1 code, Task 1 tests, and the `_light_holdout` call. `linear_steady` exposes `RECIPE = Recipe(...)` with `model_config` = Ridge/sklearn.linear_model/alpha=10.0, matching its test. The LGBM branch reuses `_lgb_params` (unchanged) + `lgb.train` exactly as the pre-refactor `_light_holdout`. `_light_holdout` keeps `_rows_on` and drops `_lgb_params`/`lgb` from its local imports.
