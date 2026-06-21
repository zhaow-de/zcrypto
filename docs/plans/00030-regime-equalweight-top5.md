# Top-5 Mega-cap Gated Basket Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `regime_equalweight_top5` (the iter-30 best, `regime_equalweight_majors`, but on the 5 mega-caps with `topk=5`) so the iter-31 closeout can A/B whether further concentration beats the 10-major basket.

**Architecture:** `regime_equalweight_majors` verbatim, changing ONLY `universe` (5 mega-caps) and `topk` (5 = the new universe size → still hold-all equal-weight).

**Tech Stack:** Python 3.12, uv, qlib, scikit-learn, pytest, ruff.

## Global Constraints

- `regime_equalweight_top5` = `regime_equalweight_majors` with two changes only: `universe = ("BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT")` and `topk=5`. `topk` MUST equal `len(universe)` (5) to stay equal-weight.
- Same `model_config` (DummyRegressor/sklearn.dummy/strategy=mean) and same gate (binary 200d, `vol_target=0.50`, `regime_benchmark="BTCUSDT"`, `n_drop=1`, `hold_thresh=5`) + same `steady` data book (handler/label/feature_config/segments/fees/cv knobs); `reference_instruments` unchanged. No `wf_enabled`. Exposes `RECIPE`.
- ruff: line length 132, double quotes. `uv run ruff check --fix` + `uv run ruff format` before commit.
- Commit: `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: `regime_equalweight_top5` recipe

**Files:**
- Create: `cli/experiment/recipes/regime_equalweight_top5.py`
- Modify: `README.md`
- Test: `tests/test_experiment_recipe.py` (extend)

**Interfaces:**
- Consumes: `Recipe`; `RegimeGatedTopkStrategy`; the iter-27 `_fit_predict` generic branch (DummyRegressor at runtime); `resolve_recipe`.
- Produces: recipe `regime_equalweight_top5`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_recipe.py`:

```python
def test_regime_equalweight_top5_is_5_megacap_basket():
    t5, mj, st = (
        resolve_recipe("regime_equalweight_top5"),
        resolve_recipe("regime_equalweight_majors"),
        resolve_recipe("steady"),
    )
    mega = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
    assert t5.universe == mega
    assert t5.strategy_config["kwargs"]["topk"] == 5 == len(t5.universe)  # hold-all equal-weight
    # everything else matches the 10-major best: model + the rest of the gate
    assert t5.model_config == mj.model_config  # DummyRegressor
    for k in ("regime_mode", "regime_ma_window", "vol_target", "regime_benchmark", "n_drop", "hold_thresh"):
        assert t5.strategy_config["kwargs"][k] == mj.strategy_config["kwargs"][k]
    # steady's data book preserved (universe is the only data-book change)
    assert t5.handler_kwargs == st.handler_kwargs
    assert t5.feature_config == st.feature_config
    assert t5.segments == st.segments
    assert t5.fee_preset == st.fee_preset and t5.label_horizon_days == st.label_horizon_days
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_experiment_recipe.py -k regime_equalweight_top5 -v`
Expected: FAIL — recipe not found.

- [ ] **Step 3: Create `cli/experiment/recipes/regime_equalweight_top5.py`**

```python
"""regime_equalweight_top5 recipe — gated equal-weight on the 5 mega-caps (concentration A/B).

iter-31 concentration point vs the iter-30 best (regime_equalweight_majors, the 10-major gated
equal-weight basket). Same DummyRegressor (no selection) + same gate (binary 200d + vol_target 0.50);
the ONLY change is the universe — the 5 most-liquid mega-caps. topk=5 = the universe size, so it
still holds all equal-weight. Tests whether further concentration beats the 10-major basket.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_equalweight_top5",
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
            "topk": 5,
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

Run: `uv run pytest tests/test_experiment_recipe.py -k regime_equalweight_top5 -v`
Expected: PASS.

- [ ] **Step 5: Update README Usage**

In `README.md` `## Usage`, add a row:
- `regime_equalweight_top5` — gated equal-weight on the 5 mega-caps (iter-31 concentration A/B vs regime_equalweight_majors).

Match the existing row format. Don't hand-edit the mdformat TOC.

- [ ] **Step 6: Lint + recipe-test run + commit**

```bash
uv run ruff check --fix cli/experiment/recipes/regime_equalweight_top5.py tests/test_experiment_recipe.py
uv run ruff format cli/experiment/recipes/regime_equalweight_top5.py tests/test_experiment_recipe.py
uv run pytest tests/test_experiment_recipe.py -q
git add cli/experiment/recipes/regime_equalweight_top5.py tests/test_experiment_recipe.py README.md
git commit -m "feat(experiment): add regime_equalweight_top5 (5-megacap gated basket)"
```

Expected: the recipe test module passes.

---

## Closeout (operational — run by the orchestrator after Task 1 lands, NOT a subagent task)

1. **Run the new arm** (redis up): `uv run zcrypto stress --recipe regime_equalweight_top5 --seeds 8`.
2. **A/B** vs `regime_equalweight_majors` (reused): per-window long-only Sharpe + mean / worst.
3. **Verdict** → `docs/iterations-history.md`: does top-5 beat top-10? Keep 10-major as the principled default unless top-5 is clearly+robustly better. Record the running best.
4. **Update `T0018`**; **README** (Task 1).
5. **iter-31 iterations-history entry.**

---

## Self-Review

**Spec coverage:** Decision 1 (regime_equalweight_top5 = regime_equalweight_majors + 5-megacap universe + topk=5) → Task 1; Decision 2 (A/B) → Closeout 1-2. README → Task 1 Step 5; verdict + T0018 + history → Closeout 3-5.

**Placeholder scan:** No TBD/TODO. The recipe file is complete code. Verdict values are closeout.

**Type consistency:** `RECIPE` exposed; `universe` has exactly 5 entries and `topk=5` matches; `model_config`/gate kwargs identical to `regime_equalweight_majors`; data book matches `steady`. The test asserts the 5-megacap universe, `topk==5==len(universe)`, model_config equality with `regime_equalweight_majors`, the shared gate kwargs, and the steady data-book guard.
