# Curated Large-cap Basket (gated equal-weight) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `regime_equalweight_majors` (the iter-29 best, `regime_equalweight`, but on a 10-major universe with `topk=10`) so the iter-30 closeout can A/B whether a curated large-cap basket beats the broad 19-coin basket.

**Architecture:** `regime_equalweight` verbatim, changing ONLY `universe` (to the 10 established majors) and `strategy_config["kwargs"]["topk"]` (10 = the new universe size → still hold-all equal-weight).

**Tech Stack:** Python 3.12, uv, qlib, scikit-learn, pytest, ruff.

## Global Constraints

- `regime_equalweight_majors` = `regime_equalweight` (iter-29) with two changes only: `universe` = `("BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","DOGEUSDT","TRXUSDT")` and `topk=10`. `topk` MUST equal `len(universe)` (10) to remain equal-weight.
- Same `model_config` (DummyRegressor/sklearn.dummy/strategy=mean) and same gate (`RegimeGatedTopkStrategy`, binary 200d, `vol_target=0.50`, `regime_benchmark="BTCUSDT"`, `n_drop=1`, `hold_thresh=5`) as `regime_equalweight`. Same `steady` data book (handler/label/feature_config/segments/fees/cv knobs); `reference_instruments` unchanged. No `wf_enabled`. Exposes `RECIPE`.
- ruff: line length 132, double quotes. `uv run ruff check --fix` + `uv run ruff format` before commit.
- Commit: `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: `regime_equalweight_majors` recipe

**Files:**
- Create: `cli/experiment/recipes/regime_equalweight_majors.py`
- Modify: `README.md`
- Test: `tests/test_experiment_recipe.py` (extend)

**Interfaces:**
- Consumes: `Recipe`; `RegimeGatedTopkStrategy`; the iter-27 `_fit_predict` generic branch (DummyRegressor at runtime); `resolve_recipe`.
- Produces: recipe `regime_equalweight_majors`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_recipe.py`:

```python
def test_regime_equalweight_majors_is_10_major_basket():
    rm, ew, st = (
        resolve_recipe("regime_equalweight_majors"),
        resolve_recipe("regime_equalweight"),
        resolve_recipe("steady"),
    )
    majors = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "TRXUSDT")
    assert rm.universe == majors
    assert rm.strategy_config["kwargs"]["topk"] == 10 == len(rm.universe)  # hold-all equal-weight
    # everything else matches regime_equalweight (the iter-29 best): model + the rest of the gate
    assert rm.model_config == ew.model_config  # DummyRegressor
    for k in ("regime_mode", "regime_ma_window", "vol_target", "regime_benchmark", "n_drop", "hold_thresh"):
        assert rm.strategy_config["kwargs"][k] == ew.strategy_config["kwargs"][k]
    # steady's data book preserved (universe is the only data-book change)
    assert rm.handler_kwargs == st.handler_kwargs
    assert rm.feature_config == st.feature_config
    assert rm.segments == st.segments
    assert rm.fee_preset == st.fee_preset and rm.label_horizon_days == st.label_horizon_days
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_experiment_recipe.py -k regime_equalweight_majors -v`
Expected: FAIL — recipe not found.

- [ ] **Step 3: Create `cli/experiment/recipes/regime_equalweight_majors.py`**

```python
"""regime_equalweight_majors recipe — gated equal-weight on the 10 established large-cap majors.

iter-30 universe A/B vs the iter-29 best (regime_equalweight, the broad 19-coin gated equal-weight
basket). Same DummyRegressor (no selection) + same gate (binary 200d + vol_target 0.50); the ONLY
change is the universe — the 10 majors with full 2020+ history (the broad basket includes thin/newer
coins absent in early OOS windows). topk=10 = the universe size, so it still holds all equal-weight.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_equalweight_majors",
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

Run: `uv run pytest tests/test_experiment_recipe.py -k regime_equalweight_majors -v`
Expected: PASS.

- [ ] **Step 5: Update README Usage**

In `README.md` `## Usage`, add a row:
- `regime_equalweight_majors` — gated equal-weight on the 10 large-cap majors (iter-30 universe A/B vs the broad regime_equalweight).

Match the existing row format. Don't hand-edit the mdformat TOC.

- [ ] **Step 6: Lint + recipe-test run + commit**

```bash
uv run ruff check --fix cli/experiment/recipes/regime_equalweight_majors.py tests/test_experiment_recipe.py
uv run ruff format cli/experiment/recipes/regime_equalweight_majors.py tests/test_experiment_recipe.py
uv run pytest tests/test_experiment_recipe.py -q
git add cli/experiment/recipes/regime_equalweight_majors.py tests/test_experiment_recipe.py README.md
git commit -m "feat(experiment): add regime_equalweight_majors (10-major gated basket)"
```

Expected: the recipe test module passes.

---

## Closeout (operational — run by the orchestrator after Task 1 lands, NOT a subagent task)

1. **Run the new arm** (redis up): `uv run zcrypto stress --recipe regime_equalweight_majors --seeds 8`.
2. **A/B** vs `regime_equalweight` (reused): per-window long-only Sharpe + mean / worst.
3. **Verdict** → `docs/iterations-history.md`: does the 10-major basket beat the broad 19-coin basket? Record the running best recipe.
4. **Update `T0018`**; **README** (Task 1).
5. **iter-30 iterations-history entry.**

---

## Self-Review

**Spec coverage:** Decision 1 (regime_equalweight_majors = regime_equalweight + 10-major universe + topk=10) → Task 1; Decision 2 (A/B) → Closeout 1-2. README → Task 1 Step 5; verdict + T0018 + history → Closeout 3-5.

**Placeholder scan:** No TBD/TODO. The recipe file is complete code. Verdict values are closeout.

**Type consistency:** `RECIPE` exposed; `universe` has exactly 10 entries and `topk=10` matches; `model_config`/gate kwargs identical to `regime_equalweight`; data book matches `steady`. The test asserts the 10-major universe, `topk==10==len(universe)`, model_config equality with `regime_equalweight`, the shared gate kwargs, and the steady data-book guard.
