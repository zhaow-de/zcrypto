# Regime Overlay Refinement (graded + vol-target) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two refinement recipes — `regime_graded` (graded gate with a chop band) and `regime_voltarget` (binary 200d gate + vol-targeting) — so the iter-24 closeout can A/B whether either beats the iter-23 binary-200d winner (`regime_steady`).

**Architecture:** Both recipes copy `steady`'s book verbatim (identical to the iter-23 `regime_fast`/`regime_cross` recipes) and change ONLY `strategy_config` to a refined `RegimeGatedTopkStrategy` (reused as-is from iter-12; its `graded`/`regime_band`/`chop_exposure`/`vol_target`/`vol_lookback` params already exist). Recipes are auto-discovered; a drift-guard test asserts each new recipe's book matches `steady` and its regime kwargs are correct.

**Tech Stack:** Python 3.12, uv, qlib, pytest, ruff.

## Global Constraints

- **Both recipes copy `steady`'s book verbatim** — the ONLY delta vs `steady` is `strategy_config`. No `wf_enabled`. Keep `topk=10, n_drop=1, hold_thresh=5` and `regime_benchmark="BTCUSDT"`, `regime_ma_window=200` (same slow gate as the iter-23 winner).
- **`regime_graded`** strategy kwargs: `regime_mode="graded"`, `regime_ma_window=200`, `regime_band=0.05`, `chop_exposure=0.5`, `vol_target=None`.
- **`regime_voltarget`** strategy kwargs: `regime_mode="binary"`, `regime_ma_window=200`, `vol_target=0.50`. (`vol_lookback` left at the strategy default 30 — do NOT set it in the recipe.)
- Each recipe module exposes a module-level `RECIPE = Recipe(...)`.
- ruff: line length 132, double quotes, import sorting. Run `uv run ruff check --fix` + `uv run ruff format` before committing.
- Commit: `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: `regime_graded` + `regime_voltarget` recipes

**Files:**
- Create: `cli/experiment/recipes/regime_graded.py`, `cli/experiment/recipes/regime_voltarget.py`
- Modify: `README.md` (Usage recipe list)
- Test: `tests/test_experiment_recipe.py` (extend)

**Interfaces:**
- Consumes: `cli.experiment.recipes.base.Recipe`; `RegimeGatedTopkStrategy` at `cli.experiment.strategies.regime` (reused, unchanged); `resolve_recipe` (auto-discovery).
- Produces: recipes resolvable as `regime_graded` / `regime_voltarget`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_experiment_recipe.py`:

```python
def test_regime_graded_is_graded_200d_band_on_steady_book():
    rg, st = resolve_recipe("regime_graded"), resolve_recipe("steady")
    sc = rg.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["regime_mode"] == "graded"
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["regime_band"] == 0.05
    assert sc["kwargs"]["chop_exposure"] == 0.5
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert sc["kwargs"]["vol_target"] is None
    assert sc["kwargs"]["topk"] == 10 and sc["kwargs"]["n_drop"] == 1 and sc["kwargs"]["hold_thresh"] == 5
    # steady's book preserved
    assert rg.universe == st.universe and rg.segments == st.segments
    assert rg.handler_kwargs["label"] == st.handler_kwargs["label"]
    assert rg.model_config["kwargs"] == st.model_config["kwargs"]
    assert rg.feature_config == st.feature_config
    assert rg.fee_preset == st.fee_preset and rg.label_horizon_days == st.label_horizon_days


def test_regime_voltarget_is_binary_200d_voltarget_on_steady_book():
    rv, st = resolve_recipe("regime_voltarget"), resolve_recipe("steady")
    sc = rv.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["regime_mode"] == "binary"
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["vol_target"] == 0.50
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert sc["kwargs"]["topk"] == 10 and sc["kwargs"]["n_drop"] == 1 and sc["kwargs"]["hold_thresh"] == 5
    # steady's book preserved
    assert rv.universe == st.universe and rv.segments == st.segments
    assert rv.handler_kwargs["label"] == st.handler_kwargs["label"]
    assert rv.model_config["kwargs"] == st.model_config["kwargs"]
    assert rv.feature_config == st.feature_config
    assert rv.fee_preset == st.fee_preset and rv.label_horizon_days == st.label_horizon_days
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_experiment_recipe.py -k "regime_graded or regime_voltarget" -v`
Expected: FAIL — recipe not found for `regime_graded` / `regime_voltarget`.

- [ ] **Step 3: Create `cli/experiment/recipes/regime_graded.py`**

```python
"""regime_graded recipe — steady's book + a GRADED 200-day-MA BTC-trend regime gate.

iter-24 refinement of the iter-23 binary-200d winner (regime_steady). The binary gate is
all-or-nothing and gave up bull-window upside; the graded gate holds full exposure above the
200-day SMA by +5%, half exposure within a +/-5% chop band, and cash below it by -5% — recovering
some of the surrendered upside near the SMA. Everything else is steady's book verbatim.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_graded",
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
        "class": "LGBModel",
        "module_path": "qlib.contrib.model.gbdt",
        "kwargs": {
            "loss": "mse",
            "num_boost_round": 1000,
            "early_stopping_rounds": 50,
            "learning_rate": 0.03,
            "num_leaves": 16,
            "max_depth": 5,
            "colsample_bytree": 0.7,
            "subsample": 0.7,
            "lambda_l1": 2.0,
            "lambda_l2": 2.0,
        },
    },
    strategy_config={
        "class": "RegimeGatedTopkStrategy",
        "module_path": "cli.experiment.strategies.regime",
        "kwargs": {
            "topk": 10,
            "n_drop": 1,
            "hold_thresh": 5,
            "regime_mode": "graded",
            "regime_benchmark": "BTCUSDT",
            "regime_ma_window": 200,
            "regime_band": 0.05,
            "chop_exposure": 0.5,
            "vol_target": None,
        },
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

- [ ] **Step 4: Create `cli/experiment/recipes/regime_voltarget.py`**

Identical to `regime_graded.py` EXCEPT the docstring, `name`, and the `strategy_config["kwargs"]` regime block. Full file:

```python
"""regime_voltarget recipe — steady's book + binary 200-day gate WITH vol-targeting.

iter-24 refinement of the iter-23 binary-200d winner (regime_steady). On top of the binary
long/cash gate, scale gross exposure down when BTC's 30-day annualized realized vol exceeds the
0.50 target (mult *= clip(vol_target/realized, <=1)) — trimming exposure in violent regimes the
plain binary gate ignores. Everything else is steady's book verbatim.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_voltarget",
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
        "class": "LGBModel",
        "module_path": "qlib.contrib.model.gbdt",
        "kwargs": {
            "loss": "mse",
            "num_boost_round": 1000,
            "early_stopping_rounds": 50,
            "learning_rate": 0.03,
            "num_leaves": 16,
            "max_depth": 5,
            "colsample_bytree": 0.7,
            "subsample": 0.7,
            "lambda_l1": 2.0,
            "lambda_l2": 2.0,
        },
    },
    strategy_config={
        "class": "RegimeGatedTopkStrategy",
        "module_path": "cli.experiment.strategies.regime",
        "kwargs": {
            "topk": 10,
            "n_drop": 1,
            "hold_thresh": 5,
            "regime_mode": "binary",
            "regime_benchmark": "BTCUSDT",
            "regime_ma_window": 200,
            "vol_target": 0.50,
        },
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

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_experiment_recipe.py -k "regime_graded or regime_voltarget" -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Update README Usage**

In `README.md` `## Usage`, find the recipe list that names `regime_fast`/`regime_cross` and add two rows:
- `regime_graded` — steady's book + a graded 200-day-MA BTC-trend regime gate (partial exposure in a ±5% chop band; iter-24 refinement).
- `regime_voltarget` — steady's book + a binary 200-day-MA gate with vol-targeting (exposure trimmed when BTC vol > 0.50; iter-24 refinement).

Match the existing row format exactly. Don't hand-edit the mdformat TOC.

- [ ] **Step 7: Lint + recipe-test run + commit**

```bash
uv run ruff check --fix cli/experiment/recipes/regime_graded.py cli/experiment/recipes/regime_voltarget.py tests/test_experiment_recipe.py
uv run ruff format cli/experiment/recipes/regime_graded.py cli/experiment/recipes/regime_voltarget.py tests/test_experiment_recipe.py
uv run pytest tests/test_experiment_recipe.py -q
git add cli/experiment/recipes/regime_graded.py cli/experiment/recipes/regime_voltarget.py tests/test_experiment_recipe.py README.md
git commit -m "feat(experiment): add regime_graded + regime_voltarget refinement recipes"
```

Expected: the recipe test module passes.

---

## Closeout (operational — run by the orchestrator after Task 1 lands, NOT a subagent task)

1. **OOS stress A/B** (redis up): `uv run zcrypto stress --recipe <r> --seeds 8` for `steady`, `regime_steady`, `regime_graded`, `regime_voltarget`; record per-window long-only Sharpe + across-window mean / worst.
2. **Verdict** → `docs/iterations-history.md`: does `regime_graded` recover bull-window upside / beat `regime_steady`'s mean 0.289? Does `regime_voltarget` improve the worst window / mean? Or is binary-200d the sweet spot?
3. **Update `T0017`** `## Findings so far` / `## Suggested next steps` with what graded + vol-target showed (trim from the open levers if settled).
4. **README** recipe list (Task 1) — confirm.
5. **iter-24 iterations-history entry** (the 2 recipes + the refinement verdict; the new best recipe if one wins).

---

## Self-Review

**Spec coverage:** Decision 1 (4 arms; 2 new recipes) → Task 1; Decision 2 (graded params) → `regime_graded.py` + its test; Decision 3 (vol-target params) → `regime_voltarget.py` + its test; Decision 4 (copy steady's book, no wf) → both files + drift tests; Decision 5 (OOS stress measurement) → Closeout 1. README → Task 1 Step 6; verdict + T0017 + history → Closeout 2-5.

**Placeholder scan:** No TBD/TODO. Both recipe files carry full code; the `regime_voltarget` "identical except" note is immediately followed by the complete file. Verdict values are correctly closeout.

**Type consistency:** Both recipes expose `RECIPE = Recipe(...)`. `strategy_config["kwargs"]` use only `RegimeGatedTopkStrategy.__init__` params (`regime_mode`, `regime_ma_window`, `regime_band`, `chop_exposure`, `regime_benchmark`, `vol_target`, plus `topk`/`n_drop`/`hold_thresh`). The test assertions reference exactly the kwargs the recipe files set. Book fields copied verbatim from `steady` (guarded by the drift tests). `regime_voltarget` deliberately omits `vol_lookback` (strategy default 30) and `regime_band`/`chop_exposure` (binary mode ignores them).
