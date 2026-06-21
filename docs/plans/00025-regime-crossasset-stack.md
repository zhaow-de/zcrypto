# Regime × Cross-asset Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `regime_crossasset_voltarget` — `crossasset_steady`'s book + the iter-24 winning regime gate — so the iter-26 closeout can A/B whether the cross-asset signal stacks with regime-timing or is redundant (like funding was).

**Architecture:** The recipe copies `crossasset_steady`'s book verbatim (incl. the `CrossAssetProcessor` prepended in `infer_processors`) and changes ONLY `strategy_config` to `RegimeGatedTopkStrategy` (binary 200d + `vol_target=0.50`). Auto-discovered; a drift-guard test asserts the book matches `crossasset_steady` and the gate kwargs are correct.

**Tech Stack:** Python 3.12, uv, qlib, pytest, ruff.

## Global Constraints

- **The recipe copies `crossasset_steady`'s book verbatim** — the ONLY delta vs `crossasset_steady` is `strategy_config`. The `infer_processors` MUST keep `CrossAssetProcessor` FIRST (then `RobustZScoreNorm`, `Fillna`). No `wf_enabled`.
- **Gate kwargs** (the iter-24 winner): `RegimeGatedTopkStrategy`, `regime_mode="binary"`, `regime_ma_window=200`, `vol_target=0.50`, `regime_benchmark="BTCUSDT"`, `topk=10/n_drop=1/hold_thresh=5`.
- Module exposes `RECIPE = Recipe(...)`.
- ruff: line length 132, double quotes, import sorting. `uv run ruff check --fix` + `uv run ruff format` before commit.
- Commit: `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: `regime_crossasset_voltarget` recipe

**Files:**
- Create: `cli/experiment/recipes/regime_crossasset_voltarget.py`
- Modify: `README.md` (Usage recipe list)
- Test: `tests/test_experiment_recipe.py` (extend)

**Interfaces:**
- Consumes: `cli.experiment.recipes.base.Recipe`; `RegimeGatedTopkStrategy` (reused); `CrossAssetProcessor` (`cli.experiment.features.cross_asset`, reused); `resolve_recipe`.
- Produces: recipe resolvable as `regime_crossasset_voltarget`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_recipe.py`:

```python
def test_regime_crossasset_voltarget_is_crossasset_book_plus_voltarget_gate():
    rc, cs = resolve_recipe("regime_crossasset_voltarget"), resolve_recipe("crossasset_steady")
    sc = rc.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["regime_mode"] == "binary"
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["vol_target"] == 0.50
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert sc["kwargs"]["topk"] == 10 and sc["kwargs"]["n_drop"] == 1 and sc["kwargs"]["hold_thresh"] == 5
    # crossasset_steady's book preserved (the CrossAssetProcessor must stay FIRST in infer_processors)
    assert rc.handler_kwargs["infer_processors"] == cs.handler_kwargs["infer_processors"]
    assert rc.handler_kwargs["infer_processors"][0]["class"] == "CrossAssetProcessor"
    assert rc.universe == cs.universe and rc.segments == cs.segments
    assert rc.handler_kwargs["label"] == cs.handler_kwargs["label"]
    assert rc.model_config["kwargs"] == cs.model_config["kwargs"]
    assert rc.feature_config == cs.feature_config
    assert rc.fee_preset == cs.fee_preset and rc.label_horizon_days == cs.label_horizon_days
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_experiment_recipe.py -k regime_crossasset_voltarget -v`
Expected: FAIL — recipe not found.

- [ ] **Step 3: Create `cli/experiment/recipes/regime_crossasset_voltarget.py`**

```python
"""regime_crossasset_voltarget recipe — crossasset_steady's book + the iter-24 winning regime gate.

iter-26 stack test: does the cross-asset relative-strength signal stack with regime-timing, or is
it redundant (as funding was in iter-25)? This is crossasset_steady's book verbatim
(CrossAssetProcessor prepended) with the strategy swapped to the iter-24 best gate
(RegimeGatedTopkStrategy, binary 200-day MA + vol-targeting at 0.50). A/B vs crossasset_steady
(ungated) and regime_voltarget (gated plain book) isolates whether cross-asset features carry
anything orthogonal to the gate's beta-timing.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_crossasset_voltarget",
    feature_config={"class": "Alpha158", "module_path": "qlib.contrib.data.handler"},
    handler_kwargs={
        # CrossAssetProcessor FIRST (verbatim from crossasset_steady) so its appended features are
        # normalized by the subsequent RobustZScoreNorm on the same scale as Alpha158's factors.
        "infer_processors": [
            {"class": "CrossAssetProcessor", "module_path": "cli.experiment.features.cross_asset", "kwargs": {}},
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

Run: `uv run pytest tests/test_experiment_recipe.py -k regime_crossasset_voltarget -v`
Expected: PASS.

- [ ] **Step 5: Update README Usage**

In `README.md` `## Usage`, find the recipe list naming `crossasset_steady` / `regime_voltarget` / `regime_funding_voltarget` and add a row:
- `regime_crossasset_voltarget` — crossasset_steady's book + a binary 200-day-MA regime gate with vol-targeting (iter-26 regime×cross-asset stack test).

Match the existing row format. Don't hand-edit the mdformat TOC.

- [ ] **Step 6: Lint + recipe-test run + commit**

```bash
uv run ruff check --fix cli/experiment/recipes/regime_crossasset_voltarget.py tests/test_experiment_recipe.py
uv run ruff format cli/experiment/recipes/regime_crossasset_voltarget.py tests/test_experiment_recipe.py
uv run pytest tests/test_experiment_recipe.py -q
git add cli/experiment/recipes/regime_crossasset_voltarget.py tests/test_experiment_recipe.py README.md
git commit -m "feat(experiment): add regime_crossasset_voltarget stack recipe"
```

Expected: the recipe test module passes.

---

## Closeout (operational — run by the orchestrator after Task 1 lands, NOT a subagent task)

1. **Run the 2 fresh arms** (redis up): `uv run zcrypto stress --recipe crossasset_steady --seeds 8` and `--recipe regime_crossasset_voltarget --seeds 8`.
2. **Assemble the 4-arm table** (reuse `steady` + `regime_voltarget` from disk): per-window long-only Sharpe + across-window mean / worst.
3. **Verdict** → `docs/iterations-history.md`: STACK (combo > `regime_voltarget` 0.311 AND > `crossasset_steady`) or REDUNDANT (combo ≤ `regime_voltarget`); does `crossasset_steady` generalize OOS at all? If feature-stacking is conclusively closed (both funding + cross-asset redundant), note the redirect.
4. **Update `T0017`** findings + next steps.
5. **README** recipe list (Task 1) — confirm.
6. **iter-26 iterations-history entry.**

---

## Self-Review

**Spec coverage:** Decision 1 (combo recipe) → Task 1; Decision 2 (4-arm A/B, 2 reused) → Closeout 1-2; Decision 3 (copy crossasset_steady book, no wf, drift-guard) → recipe file + test. README → Task 1 Step 5; verdict + T0017 + history → Closeout 3-6.

**Placeholder scan:** No TBD/TODO. Recipe file is complete code. Verdict values are closeout.

**Type consistency:** Recipe exposes `RECIPE = Recipe(...)`. `infer_processors` keeps `CrossAssetProcessor` first (verbatim from `crossasset_steady`); `strategy_config` uses `RegimeGatedTopkStrategy.__init__` params. The test drift-guards the full `infer_processors` list + book fields against `resolve_recipe("crossasset_steady")` and asserts the gate kwargs. (Note: `crossasset_steady` lists `feature_config` before `handler_kwargs` in the Recipe call; field order is irrelevant for the dataclass — the recipe copies the same field values.)
