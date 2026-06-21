# Regime-gated Equal-weight (selection-value test) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `regime_equalweight` — a no-selection book (constant signal + hold-the-universe) with the iter-24 regime gate — so the iter-29 closeout can A/B whether the Alpha158 selection adds any OOS value over regime-gated equal-weight.

**Architecture:** The recipe copies `steady`'s book, swapping `model_config` to a `DummyRegressor` (constant prediction → no cross-sectional ranking, via the iter-27 `_fit_predict` generic branch) and `strategy_config` to `RegimeGatedTopkStrategy` with `topk=19` (= the 19-coin universe → hold all, equal-weight) + the iter-24 gate. Auto-discovered; drift-guard test.

**Tech Stack:** Python 3.12, uv, qlib, scikit-learn (DummyRegressor), pytest, ruff.

## Global Constraints

- **`model_config`** = `{"class": "DummyRegressor", "module_path": "sklearn.dummy", "kwargs": {"strategy": "mean"}}` — a constant signal (no selection); runs via the iter-27 `_fit_predict` generic sklearn branch.
- **`strategy_config`** = `RegimeGatedTopkStrategy` with `topk=19` (the universe size → hold all equal-weight), `n_drop=1`, `hold_thresh=5`, `regime_mode="binary"`, `regime_benchmark="BTCUSDT"`, `regime_ma_window=200`, `vol_target=0.50` — IDENTICAL gate to `regime_voltarget`; the only difference vs `regime_voltarget` is the model (DummyRegressor vs LGBM) + `topk` (19 vs 10).
- Everything else (handler_kwargs, label, feature_config, segments, universe, fees, etc.) is `steady`'s book verbatim. No `wf_enabled`. Module exposes `RECIPE = Recipe(...)`.
- ruff: line length 132, double quotes, import sorting. `uv run ruff check --fix` + `uv run ruff format` before commit.
- Commit: `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: `regime_equalweight` recipe

**Files:**
- Create: `cli/experiment/recipes/regime_equalweight.py`
- Modify: `README.md`
- Test: `tests/test_experiment_recipe.py` (extend)

**Interfaces:**
- Consumes: `Recipe`; `RegimeGatedTopkStrategy` (reused); the iter-27 `_fit_predict` generic branch (runtime, for DummyRegressor); `resolve_recipe`.
- Produces: recipe `regime_equalweight`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_recipe.py`:

```python
def test_regime_equalweight_is_no_selection_gated_universe():
    ew, st = resolve_recipe("regime_equalweight"), resolve_recipe("steady")
    mc = ew.strategy_config
    assert ew.model_config == {"class": "DummyRegressor", "module_path": "sklearn.dummy", "kwargs": {"strategy": "mean"}}
    assert mc["class"] == "RegimeGatedTopkStrategy"
    assert mc["module_path"] == "cli.experiment.strategies.regime"
    assert mc["kwargs"]["topk"] == 19  # = universe size -> hold all -> equal-weight
    assert mc["kwargs"]["regime_mode"] == "binary"
    assert mc["kwargs"]["regime_ma_window"] == 200
    assert mc["kwargs"]["vol_target"] == 0.50
    assert mc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert len(ew.universe) == 19  # topk == universe size
    # steady's data book preserved (only model + strategy differ)
    assert ew.handler_kwargs == st.handler_kwargs
    assert ew.feature_config == st.feature_config
    assert ew.universe == st.universe and ew.segments == st.segments
    assert ew.fee_preset == st.fee_preset and ew.label_horizon_days == st.label_horizon_days
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_experiment_recipe.py -k regime_equalweight -v`
Expected: FAIL — recipe not found.

- [ ] **Step 3: Create `cli/experiment/recipes/regime_equalweight.py`**

```python
"""regime_equalweight recipe — a NO-SELECTION book (hold the whole universe equal-weight) + the gate.

iter-29 selection-value test: how much of regime_voltarget's OOS edge is the Alpha158 cross-sectional
selection vs the BTC-trend market-timing? This recipe removes the selection entirely — a DummyRegressor
emits a constant signal (no ranking; runs via the iter-27 _fit_predict generic branch) and
RegimeGatedTopkStrategy with topk=19 (the universe size) holds all names equal-weight. The gate is
identical to regime_voltarget (binary 200d + vol_target 0.50), so the A/B isolates selection vs none.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_equalweight",
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
        "class": "DummyRegressor",
        "module_path": "sklearn.dummy",
        "kwargs": {"strategy": "mean"},
    },
    strategy_config={
        "class": "RegimeGatedTopkStrategy",
        "module_path": "cli.experiment.strategies.regime",
        "kwargs": {
            "topk": 19,
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

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_experiment_recipe.py -k regime_equalweight -v`
Expected: PASS.

- [ ] **Step 5: Update README Usage**

In `README.md` `## Usage`, add a row:
- `regime_equalweight` — no-selection baseline: hold the whole universe equal-weight (constant signal + topk=19) under the same regime gate as regime_voltarget (iter-29 selection-value test).

Match the existing row format. Don't hand-edit the mdformat TOC.

- [ ] **Step 6: Lint + recipe-test run + commit**

```bash
uv run ruff check --fix cli/experiment/recipes/regime_equalweight.py tests/test_experiment_recipe.py
uv run ruff format cli/experiment/recipes/regime_equalweight.py tests/test_experiment_recipe.py
uv run pytest tests/test_experiment_recipe.py -q
git add cli/experiment/recipes/regime_equalweight.py tests/test_experiment_recipe.py README.md
git commit -m "feat(experiment): add regime_equalweight no-selection baseline recipe"
```

Expected: the recipe test module passes.

---

## Closeout (operational — run by the orchestrator after Task 1 lands, NOT a subagent task)

1. **Run the new arm** (redis up): `uv run zcrypto stress --recipe regime_equalweight --seeds 8`.
2. **A/B** vs `regime_voltarget` (reused from disk): per-window long-only Sharpe + mean / worst.
3. **Verdict** → `docs/iterations-history.md`: `regime_equalweight` ≈ `regime_voltarget` → selection adds nothing OOS (edge is pure market-timing; strategy simplifies to gated equal-weight). `regime_voltarget` > `regime_equalweight` → selection adds value; quantify.
4. **Update `T0018`** (selection vs timing share of the edge).
5. **README** recipe list (Task 1) — confirm.
6. **iter-29 iterations-history entry.**

---

## Self-Review

**Spec coverage:** Decision 1 (regime_equalweight = DummyRegressor + RegimeGatedTopkStrategy topk=19 + the gate) → Task 1; Decision 2 (A/B vs regime_voltarget) → Closeout 1-2. README → Task 1 Step 5; verdict + T0018 + history → Closeout 3-6.

**Placeholder scan:** No TBD/TODO. The recipe file is complete code. Verdict values are closeout.

**Type consistency:** Recipe exposes `RECIPE = Recipe(...)`. `model_config` (DummyRegressor/sklearn.dummy/strategy=mean) runs via the iter-27 `_fit_predict` generic branch (DummyRegressor has `.fit(X,y)`/`.predict(X)` → constant). `strategy_config` uses `RegimeGatedTopkStrategy.__init__` params (`regime_mode`/`regime_ma_window`/`vol_target`/`regime_benchmark` + `topk`/`n_drop`/`hold_thresh`); `topk=19` equals `len(universe)`. The test asserts the model_config dict, the strategy kwargs (incl. topk=19), `len(universe)==19`, and drift-guards the data book against `resolve_recipe("steady")`.
