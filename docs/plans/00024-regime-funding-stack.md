# Regime × Funding Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `regime_funding_voltarget` — `funding_steady`'s book + the iter-24 winning regime gate — so the iter-25 closeout can A/B whether regime-timing stacks with the funding signal or is redundant.

**Architecture:** The recipe copies `funding_steady`'s book verbatim (incl. the `FundingRateProcessor` prepended in `infer_processors`) and changes ONLY `strategy_config` to `RegimeGatedTopkStrategy` (binary 200d + `vol_target=0.50` — the iter-24 best gate). Auto-discovered; a drift-guard test asserts the book matches `funding_steady` and the gate kwargs are correct.

**Tech Stack:** Python 3.12, uv, qlib, pytest, ruff.

## Global Constraints

- **The recipe copies `funding_steady`'s book verbatim** — the ONLY delta vs `funding_steady` is `strategy_config`. The `infer_processors` MUST keep `FundingRateProcessor` FIRST (then `RobustZScoreNorm`, `Fillna`), exactly as `funding_steady`. No `wf_enabled`.
- **Gate kwargs** (the iter-24 `regime_voltarget` winner): `RegimeGatedTopkStrategy`, `regime_mode="binary"`, `regime_ma_window=200`, `vol_target=0.50`, `regime_benchmark="BTCUSDT"`, `topk=10/n_drop=1/hold_thresh=5`.
- Module exposes `RECIPE = Recipe(...)`.
- ruff: line length 132, double quotes, import sorting. `uv run ruff check --fix` + `uv run ruff format` before commit.
- Commit: `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: `regime_funding_voltarget` recipe

**Files:**
- Create: `cli/experiment/recipes/regime_funding_voltarget.py`
- Modify: `README.md` (Usage recipe list)
- Test: `tests/test_experiment_recipe.py` (extend)

**Interfaces:**
- Consumes: `cli.experiment.recipes.base.Recipe`; `RegimeGatedTopkStrategy` (`cli.experiment.strategies.regime`, reused); `FundingRateProcessor` (`cli.experiment.features.funding`, reused); `resolve_recipe`.
- Produces: recipe resolvable as `regime_funding_voltarget`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_recipe.py`:

```python
def test_regime_funding_voltarget_is_funding_book_plus_voltarget_gate():
    rf, fs = resolve_recipe("regime_funding_voltarget"), resolve_recipe("funding_steady")
    sc = rf.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["regime_mode"] == "binary"
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["vol_target"] == 0.50
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert sc["kwargs"]["topk"] == 10 and sc["kwargs"]["n_drop"] == 1 and sc["kwargs"]["hold_thresh"] == 5
    # funding_steady's book preserved (the FundingRateProcessor must stay FIRST in infer_processors)
    assert rf.handler_kwargs["infer_processors"] == fs.handler_kwargs["infer_processors"]
    assert rf.handler_kwargs["infer_processors"][0]["class"] == "FundingRateProcessor"
    assert rf.universe == fs.universe and rf.segments == fs.segments
    assert rf.handler_kwargs["label"] == fs.handler_kwargs["label"]
    assert rf.model_config["kwargs"] == fs.model_config["kwargs"]
    assert rf.feature_config == fs.feature_config
    assert rf.fee_preset == fs.fee_preset and rf.label_horizon_days == fs.label_horizon_days
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_experiment_recipe.py -k regime_funding_voltarget -v`
Expected: FAIL — recipe not found.

- [ ] **Step 3: Create `cli/experiment/recipes/regime_funding_voltarget.py`**

```python
"""regime_funding_voltarget recipe — funding_steady's book + the iter-24 winning regime gate.

iter-25 stack test: does regime-timing stack with the funding signal, or are they redundant?
This is funding_steady's book verbatim (FundingRateProcessor prepended) with the strategy swapped
to the iter-24 best gate (RegimeGatedTopkStrategy, binary 200-day MA + vol-targeting at 0.50).
A/B vs funding_steady (the ungated funding book) and regime_voltarget (the gated plain book)
isolates whether funding carries anything orthogonal to the gate's beta-timing.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_funding_voltarget",
    handler_kwargs={
        # FundingRateProcessor FIRST (verbatim from funding_steady) so its appended features are
        # normalized by the subsequent RobustZScoreNorm on the same scale as Alpha158's factors.
        "infer_processors": [
            {"class": "FundingRateProcessor", "module_path": "cli.experiment.features.funding", "kwargs": {}},
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

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_experiment_recipe.py -k regime_funding_voltarget -v`
Expected: PASS.

- [ ] **Step 5: Update README Usage**

In `README.md` `## Usage`, find the recipe list naming `funding_steady` / `regime_voltarget` and add a row:
- `regime_funding_voltarget` — funding_steady's book + a binary 200-day-MA regime gate with vol-targeting (iter-25 regime×funding stack test).

Match the existing row format. Don't hand-edit the mdformat TOC.

- [ ] **Step 6: Lint + recipe-test run + commit**

```bash
uv run ruff check --fix cli/experiment/recipes/regime_funding_voltarget.py tests/test_experiment_recipe.py
uv run ruff format cli/experiment/recipes/regime_funding_voltarget.py tests/test_experiment_recipe.py
uv run pytest tests/test_experiment_recipe.py -q
git add cli/experiment/recipes/regime_funding_voltarget.py tests/test_experiment_recipe.py README.md
git commit -m "feat(experiment): add regime_funding_voltarget stack recipe"
```

Expected: the recipe test module passes.

---

## Closeout (operational — run by the orchestrator after Task 1 lands, NOT a subagent task)

1. **Run the new arm** (redis up): `uv run zcrypto stress --recipe regime_funding_voltarget --seeds 8`.
2. **Assemble the 4-arm table** from the existing stress bundles for `steady`, `funding_steady`, `regime_voltarget` + the new `regime_funding_voltarget`: per-window long-only Sharpe + across-window mean / worst.
3. **Verdict** → `docs/iterations-history.md`: STACK (combo mean > `regime_voltarget` 0.311 AND > `funding_steady` → funding is orthogonal to the gate → new best) or REDUNDANT (combo ≈ `regime_voltarget` → funding's edge is the beta-timing the gate already supplies → confirms iter-21).
4. **Update `T0017`** findings + next steps.
5. **README** recipe list (Task 1) — confirm.
6. **iter-25 iterations-history entry.**

---

## Self-Review

**Spec coverage:** Decision 1 (combo recipe = funding book + voltarget gate) → Task 1; Decision 2 (4-arm OOS A/B, 3 reused) → Closeout 1-2; Decision 3 (copy funding_steady's book, no wf, drift-guard) → recipe file + the test. README → Task 1 Step 5; verdict + T0017 + history → Closeout 3-6.

**Placeholder scan:** No TBD/TODO. The recipe file is complete code. Verdict values are correctly closeout.

**Type consistency:** Recipe exposes `RECIPE = Recipe(...)`. `infer_processors` keeps `FundingRateProcessor` first (verbatim from `funding_steady`); `strategy_config` uses `RegimeGatedTopkStrategy.__init__` params (`regime_mode`, `regime_ma_window`, `vol_target`, `regime_benchmark`, plus `topk`/`n_drop`/`hold_thresh`). The test drift-guards the full `infer_processors` list + book fields against `resolve_recipe("funding_steady")` and asserts the gate kwargs the recipe sets.
