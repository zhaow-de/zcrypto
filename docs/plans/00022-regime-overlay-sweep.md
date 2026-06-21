# Regime-overlay Responsiveness Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two more-responsive BTC-trend regime recipes — `regime_fast` (binary 100-day MA) and `regime_cross` (50/200-day SMA golden-cross) — so the iter-23 closeout can A/B whether a faster gate defends the bear regimes where iter-12's slow binary-200d gate failed.

**Architecture:** Both recipes copy `steady`'s book verbatim (Alpha158 / regularized LGBM / 5-day label / segments / universe / fees) and change ONLY `strategy_config` to `RegimeGatedTopkStrategy` (iter-12, `cli.experiment.strategies.regime`) with a faster gate. Recipes are auto-discovered (`resolve_recipe` globs the recipes dir for modules exposing `RECIPE`), so no registry edit is needed. A drift-guard test (mirroring the existing `regime_steady` test) asserts each new recipe's book matches `steady` and its regime kwargs are correct.

**Tech Stack:** Python 3.12, uv, qlib, pytest, ruff.

## Global Constraints

- **Both recipes copy `steady`'s book verbatim** — the ONLY delta vs `steady` is `strategy_config`. No `wf_enabled` (match `steady`; the multi-seed holdout ignores it anyway). This keeps the closeout A/B a clean isolation of the regime gate.
- **`RegimeGatedTopkStrategy` kwargs** (reused as-is from iter-12): `regime_mode` ∈ {`binary`, `cross`}; `binary` uses `regime_ma_window`; `cross` requires `regime_ma_fast` (fast SMA) + `regime_ma_window` (slow SMA); `regime_benchmark="BTCUSDT"`; `vol_target=None`. Keep `topk=10, n_drop=1, hold_thresh=5` (identical to `steady`/`regime_steady`).
- Each recipe module exposes a module-level `RECIPE = Recipe(...)`.
- ruff: line length 132, double quotes, import sorting. Run `uv run ruff check --fix` + `uv run ruff format` before committing.
- Commit: `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: `regime_fast` + `regime_cross` recipes

**Files:**
- Create: `cli/experiment/recipes/regime_fast.py`, `cli/experiment/recipes/regime_cross.py`
- Modify: `README.md` (Usage recipe list)
- Test: `tests/test_experiment_recipe.py` (extend)

**Interfaces:**
- Consumes: `cli.experiment.recipes.base.Recipe`; `RegimeGatedTopkStrategy` at `cli.experiment.strategies.regime` (reused, unchanged); `resolve_recipe` (auto-discovery).
- Produces: recipes resolvable as `regime_fast` / `regime_cross`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_experiment_recipe.py`:

```python
def test_regime_fast_is_binary_100d_gate_on_steady_book():
    rf, st = resolve_recipe("regime_fast"), resolve_recipe("steady")
    sc = rf.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["regime_mode"] == "binary"
    assert sc["kwargs"]["regime_ma_window"] == 100  # faster than regime_steady's 200
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert sc["kwargs"]["vol_target"] is None
    assert sc["kwargs"]["topk"] == 10 and sc["kwargs"]["n_drop"] == 1 and sc["kwargs"]["hold_thresh"] == 5
    # steady's book preserved (clean A/B; the gate is the only change)
    assert rf.universe == st.universe and rf.segments == st.segments
    assert rf.handler_kwargs["label"] == st.handler_kwargs["label"]
    assert rf.model_config["kwargs"] == st.model_config["kwargs"]
    assert rf.feature_config == st.feature_config
    assert rf.fee_preset == st.fee_preset and rf.label_horizon_days == st.label_horizon_days


def test_regime_cross_is_50_200_cross_gate_on_steady_book():
    rc, st = resolve_recipe("regime_cross"), resolve_recipe("steady")
    sc = rc.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["regime_mode"] == "cross"
    assert sc["kwargs"]["regime_ma_fast"] == 50
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert sc["kwargs"]["vol_target"] is None
    assert sc["kwargs"]["topk"] == 10 and sc["kwargs"]["n_drop"] == 1 and sc["kwargs"]["hold_thresh"] == 5
    # steady's book preserved
    assert rc.universe == st.universe and rc.segments == st.segments
    assert rc.handler_kwargs["label"] == st.handler_kwargs["label"]
    assert rc.model_config["kwargs"] == st.model_config["kwargs"]
    assert rc.feature_config == st.feature_config
    assert rc.fee_preset == st.fee_preset and rc.label_horizon_days == st.label_horizon_days
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_experiment_recipe.py -k "regime_fast or regime_cross" -v`
Expected: FAIL — `ValueError`/recipe not found for `regime_fast` / `regime_cross`.

- [ ] **Step 3: Create `cli/experiment/recipes/regime_fast.py`**

```python
"""regime_fast recipe — steady's book + a FASTER (100-day MA) binary BTC-trend regime gate.

iter-23 responsiveness sweep. iter-12's regime_steady used a 200-day MA gate that "rarely
engaged" (BTC was mostly above its slow 200-day MA), so it behaved like steady. regime_fast
halves the MA window to 100 days so the gate engages sooner in downturns. Everything else is
steady's book verbatim, so the A/B (vs steady and vs regime_steady) isolates gate responsiveness.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_fast",
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
            "regime_ma_window": 100,
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

- [ ] **Step 4: Create `cli/experiment/recipes/regime_cross.py`**

Identical to `regime_fast.py` EXCEPT the docstring and the `strategy_config["kwargs"]` regime block. Full file:

```python
"""regime_cross recipe — steady's book + a 50/200-day SMA golden-cross BTC-trend regime gate.

iter-23 responsiveness sweep. The classic trend-following signal: long the book only while the
50-day SMA of BTC is above its 200-day SMA (golden cross), flat otherwise (death cross). More
responsive than regime_steady's level-vs-200d gate, less whippy than a fast level gate.
Everything else is steady's book verbatim, so the A/B isolates the gate.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_cross",
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
            "regime_mode": "cross",
            "regime_benchmark": "BTCUSDT",
            "regime_ma_fast": 50,
            "regime_ma_window": 200,
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

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_experiment_recipe.py -k "regime_fast or regime_cross" -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Update README Usage**

In `README.md` `## Usage`, find the recipe list/table that already names `regime_steady` (and `steady`, `funding_steady`, etc.) and add two rows:
- `regime_fast` — steady's book + a faster binary 100-day-MA BTC-trend regime gate (iter-23 responsiveness sweep).
- `regime_cross` — steady's book + a 50/200-day SMA golden-cross BTC-trend regime gate (iter-23 responsiveness sweep).

Match the existing row format exactly. Don't hand-edit the mdformat TOC.

- [ ] **Step 7: Lint + full recipe-test run + commit**

```bash
uv run ruff check --fix cli/experiment/recipes/regime_fast.py cli/experiment/recipes/regime_cross.py tests/test_experiment_recipe.py
uv run ruff format cli/experiment/recipes/regime_fast.py cli/experiment/recipes/regime_cross.py tests/test_experiment_recipe.py
uv run pytest tests/test_experiment_recipe.py -q
git add cli/experiment/recipes/regime_fast.py cli/experiment/recipes/regime_cross.py tests/test_experiment_recipe.py README.md
git commit -m "feat(experiment): add regime_fast + regime_cross responsiveness recipes"
```

Expected: the recipe test module passes.

---

## Closeout (operational — run by the orchestrator after Task 1 lands, NOT a subagent task)

1. **Holdout A/B** (redis up via `scripts/redis.sh start`): for each of `steady`, `regime_steady`, `regime_fast`, `regime_cross`, run the multi-seed holdout (`run_holdout_seeds`, `--seeds 8 --deterministic`) and record per-seed **cost-adjusted Sharpe** (NOT gross `ending_value`, per `T0015`) + the paired Δ(regime − steady).
2. **OOS stress** for each arm: `uv run zcrypto stress --recipe <r> --seeds 8` → per-window long-only Sharpe (2022/2023/2024/2025) + across-window mean / worst.
3. **Verdict** → `docs/iterations-history.md`: does any regime arm improve risk-adjusted return vs `steady` — especially lift the bear windows (2022, 2025) toward 0/positive while preserving the bull window (2023 +1.24), i.e. a net-positive market-timed long book? Does a faster gate (100d / 50-200 cross) engage where the slow 200d did not? Or is the null confirmed under current methodology?
4. **`T0003`** stays resolved/archived — note the measured follow-up in the history entry; do NOT un-archive.
5. **README** recipe list (Task 1) — confirm.
6. **iter-23 iterations-history entry** (the 2 recipes + the responsiveness verdict).
7. If a regime configuration helps, open a **new** `docs/open-topics/` topic for the follow-up (graded/vol-target tuning, or regime-gating a market-neutral book).

---

## Self-Review

**Spec coverage:** Decision 1 (4 arms; 2 new recipes) → Task 1 (`regime_fast` binary-100d, `regime_cross` cross-50/200); Decision 2 (copy steady's book, no wf) → both recipe files + the drift-guard tests; Decision 3 (holdout + OOS-stress A/B) → Closeout 1-2; Decision 4 (holdout uses recipe strategy) → relied on (no code change); Decision 5 (defer graded/vol-target) → not built, noted in Closeout 7. README → Task 1 Step 6; verdict + T0003 + history → Closeout 3-6.

**Placeholder scan:** No TBD/TODO. Both recipe files carry full code; the only `regime_cross` "identical except" note is immediately followed by the complete file. Verdict values are correctly closeout (the runs).

**Type consistency:** Both recipes expose `RECIPE = Recipe(...)` (matches `resolve_recipe`). `strategy_config` shape matches `RegimeGatedTopkStrategy.__init__` params read from `cli/experiment/strategies/regime.py` (`regime_mode`, `regime_ma_window`, `regime_ma_fast`, `regime_benchmark`, `vol_target`, plus `topk`/`n_drop`/`hold_thresh`). The test assertions reference exactly the kwargs the recipe files set. Book fields copied verbatim from `steady` (guarded by the drift test).
