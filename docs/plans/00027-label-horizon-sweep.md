# Label-horizon Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the stress harness's purge scale with the recipe's label horizon (a leak-safety fix) and add 1/10/20-day label recipes, so the iter-28 closeout can A/B whether any forecast horizon generalizes OOS where 5-day inverts.

**Architecture:** Task 1 fixes `cli/stress/command.py` to pass `purge_days = max(PURGE_DAYS, recipe.label_horizon_days + 2)` (leak-safe for any horizon; unchanged for horizon ≤ 6). Task 2 adds `h1_steady`/`h10_steady`/`h20_steady` — `steady`'s book verbatim with only the label expression + `label_horizon_days` changed.

**Tech Stack:** Python 3.12, uv, qlib, pytest, ruff.

## Global Constraints

- **The purge fix must not change behavior for existing recipes:** `max(PURGE_DAYS, label_horizon_days + 2)` = `max(8, ≤8) = 8` for every `label_horizon_days ≤ 6` recipe → identical windows → no regression. It only grows for the new long-horizon recipes.
- **`label_horizon_days` MUST equal the max forward `Ref`** in each recipe's label (the leak-free-purge invariant): h1 → label `Ref($close,-2)/Ref($close,-1)-1`, `label_horizon_days=2`; h10 → `Ref($close,-11)/...`, `11`; h20 → `Ref($close,-21)/...`, `21`.
- Each recipe copies `steady`'s book verbatim except `handler_kwargs["label"]` and `label_horizon_days`. No `wf_enabled`. Each exposes `RECIPE = Recipe(...)`.
- ruff: line length 132, double quotes, import sorting. `uv run ruff check --fix` + `uv run ruff format` before commit.
- Commit: `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: stress purge scales with the label horizon

**Files:**
- Modify: `cli/experiment/../stress/command.py` (i.e. `cli/stress/command.py`)
- Test: `tests/test_stress_command.py` (extend)

**Interfaces:**
- Consumes: `cli.stress.windows.PURGE_DAYS` + `build_oos_windows` (the `purge_days` param already exists).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_stress_command.py` (it already has a `_patch` helper that monkeypatches `resolve_recipe`/`load_config`/`resolve_data_dir`/`load_index`/`run_holdout_seeds` and a `_fake_holdout` that captures each window's `(train, test)` into `seen`). Add a test that a long-horizon recipe widens the purge:

```python
def test_stress_purge_scales_with_label_horizon(monkeypatch, tmp_path):
    import datetime as dt

    seen = []
    _patch(monkeypatch, tmp_path, seen)
    # override the patched recipe with a long-horizon one (label_horizon_days=20)
    import cli.stress.command as cmd

    class _LongRecipe:
        name = "h20_steady"
        segments = {"train": ("2020-01-01", "2023-12-31"), "valid": ("2024-01-01", "2024-12-31"), "test": ("2025-01-01", "2026-06-15")}
        label_horizon_days = 20

    monkeypatch.setattr(cmd, "resolve_recipe", lambda name: _LongRecipe())
    out = tmp_path / "runs"
    result = runner.invoke(app, ["stress", "--recipe", "h20_steady", "--seeds", "1", "--out", str(out)])
    assert result.exit_code == 0, result.stdout
    # every window's train_end must be >= 20 days before its test_start (purge >= horizon)
    for train, test in seen:
        gap = (dt.date.fromisoformat(test[0]) - dt.date.fromisoformat(train[1])).days
        assert gap >= 20, f"purge {gap}d < label horizon 20d (leak)"
```

(If `_patch` / `_fake_holdout` / `runner` are named differently, adapt to the existing fixtures in the file — the key assertion is the ≥20-day train→test gap.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_stress_command.py -k purge_scales -v`
Expected: FAIL — the gap is 8 (the hardcoded default), < 20.

- [ ] **Step 3: Apply the fix in `cli/stress/command.py`**

Change the import:
```python
from cli.stress.windows import build_oos_windows
```
to:
```python
from cli.stress.windows import PURGE_DAYS, build_oos_windows
```

And change the window-build (the `data_end = ...` / `windows = build_oos_windows(...)` lines) to:
```python
    data_end = (_dt.date.fromisoformat(idx.calendar.to_date) - _dt.timedelta(days=_BACKTEST_TAIL_BUFFER_DAYS)).isoformat()
    purge_days = max(PURGE_DAYS, recipe.label_horizon_days + 2)
    windows = build_oos_windows(
        _TEST_STARTS, data_start=idx.calendar.from_date, data_end=data_end, purge_days=purge_days
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_stress_command.py -q`
Expected: PASS — the new purge test passes AND the existing stress-command tests still pass (their `_Recipe` has `label_horizon_days=6` → purge stays 8 → their window assertions are unchanged).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix cli/stress/command.py tests/test_stress_command.py
uv run ruff format cli/stress/command.py tests/test_stress_command.py
git add cli/stress/command.py tests/test_stress_command.py
git commit -m "fix(stress): scale the OOS purge with the recipe's label horizon"
```

---

### Task 2: `h1_steady` / `h10_steady` / `h20_steady` recipes

**Files:**
- Create: `cli/experiment/recipes/h1_steady.py`, `h10_steady.py`, `h20_steady.py`
- Modify: `README.md`
- Test: `tests/test_experiment_recipe.py` (extend)

**Interfaces:**
- Consumes: `cli.experiment.recipes.base.Recipe`; `resolve_recipe`.
- Produces: recipes `h1_steady` / `h10_steady` / `h20_steady`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_experiment_recipe.py`:

```python
import pytest


@pytest.mark.parametrize(
    "name,fwd,horizon",
    [("h1_steady", 2, 2), ("h10_steady", 11, 11), ("h20_steady", 21, 21)],
)
def test_horizon_recipe_is_steady_book_with_changed_label(name, fwd, horizon):
    r, st = resolve_recipe(name), resolve_recipe("steady")
    assert r.handler_kwargs["label"] == ([f"Ref($close, -{fwd})/Ref($close, -1) - 1"], ["LABEL0"])
    assert r.label_horizon_days == horizon
    # rest of steady's book preserved
    assert r.model_config == st.model_config
    assert r.strategy_config == st.strategy_config
    assert r.feature_config == st.feature_config
    assert r.handler_kwargs["infer_processors"] == st.handler_kwargs["infer_processors"]
    assert r.handler_kwargs["learn_processors"] == st.handler_kwargs["learn_processors"]
    assert r.universe == st.universe and r.segments == st.segments
    assert r.fee_preset == st.fee_preset
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_experiment_recipe.py -k horizon_recipe -v`
Expected: FAIL — recipes not found.

- [ ] **Step 3: Create `cli/experiment/recipes/h1_steady.py`**

```python
"""h1_steady recipe — steady's book with a 1-day label (vs steady's 5-day).

iter-28 label-horizon sweep: does a different forecast horizon generalize OOS where the 5-day
label inverts on 2025+? Everything except the label + label_horizon_days is steady's book verbatim.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="h1_steady",
    handler_kwargs={
        "infer_processors": [
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
        "label": (["Ref($close, -2)/Ref($close, -1) - 1"], ["LABEL0"]),
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
    label_horizon_days=2,
    feature_lookback_days=60,
    cv_n_groups=6,
    cv_test_groups=2,
)
```

- [ ] **Step 4: Create `h10_steady.py` and `h20_steady.py`**

Both are **byte-identical to `h1_steady.py`** except the module docstring's "1-day"→"10-day"/"20-day", and these three values:

`cli/experiment/recipes/h10_steady.py`:
- `name="h10_steady"`
- `"label": (["Ref($close, -11)/Ref($close, -1) - 1"], ["LABEL0"])`
- `label_horizon_days=11`

`cli/experiment/recipes/h20_steady.py`:
- `name="h20_steady"`
- `"label": (["Ref($close, -21)/Ref($close, -1) - 1"], ["LABEL0"])`
- `label_horizon_days=21`

Everything else (model_config, strategy_config, feature_config, segments, universe, reference_instruments, account, benchmark, fee_preset, feature_lookback_days, cv_n_groups, cv_test_groups, the two processor lists) is identical to `h1_steady.py`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_experiment_recipe.py -k horizon_recipe -v`
Expected: PASS (3 parametrized cases).

- [ ] **Step 6: Update README Usage**

In `README.md` `## Usage`, add three rows to the recipe list:
- `h1_steady` — steady's book with a 1-day label (iter-28 horizon sweep).
- `h10_steady` — steady's book with a 10-day label (iter-28 horizon sweep).
- `h20_steady` — steady's book with a 20-day label (iter-28 horizon sweep).

Match the existing row format. Don't hand-edit the mdformat TOC.

- [ ] **Step 7: Lint + recipe-test run + commit**

```bash
uv run ruff check --fix cli/experiment/recipes/h1_steady.py cli/experiment/recipes/h10_steady.py cli/experiment/recipes/h20_steady.py tests/test_experiment_recipe.py
uv run ruff format cli/experiment/recipes/h1_steady.py cli/experiment/recipes/h10_steady.py cli/experiment/recipes/h20_steady.py tests/test_experiment_recipe.py
uv run pytest tests/test_experiment_recipe.py -q
git add cli/experiment/recipes/h1_steady.py cli/experiment/recipes/h10_steady.py cli/experiment/recipes/h20_steady.py tests/test_experiment_recipe.py README.md
git commit -m "feat(experiment): add h1/h10/h20_steady label-horizon recipes"
```

Expected: the recipe test module passes.

---

## Closeout (operational — run by the orchestrator after Tasks 1-2 land, NOT a subagent task)

1. **Run the 3 horizon recipes** (redis up): `uv run zcrypto stress --recipe h1_steady --seeds 8`, `--recipe h10_steady`, `--recipe h20_steady`. (`steady` 5d reused from disk.)
2. **Assemble the table:** per-window long-only Sharpe + mean / worst for `steady` (5d) / `h1` / `h10` / `h20`.
3. **Verdict** → `docs/iterations-history.md`: does any horizon avoid the 2025 inversion / beat `steady`'s 0.154? → a lead (gate it next). If all invert → the wall (T0018) is airtight across inputs/fitter/target.
4. **Update `T0018`** with the target-axis result.
5. **README** recipe list (Task 2) — confirm.
6. **iter-28 iterations-history entry** (the purge fix + the horizon verdict).

---

## Self-Review

**Spec coverage:** Decision 1 (purge scales) → Task 1; Decision 2 (3 horizon recipes) → Task 2; Decision 3 (ungated A/B) → Closeout 1-2. README → Task 2 Step 6; verdict + T0018 + history → Closeout 3-6.

**Placeholder scan:** No TBD/TODO. Task 1 shows the exact import + window-build change. Task 2 gives `h1_steady` in full + the exact 3-value deltas for h10/h20. Verdict values are closeout.

**Type consistency:** The fix uses `recipe.label_horizon_days` (a `Recipe` field) + `PURGE_DAYS` (imported) + `build_oos_windows(..., purge_days=)` (existing param). Each recipe exposes `RECIPE`; the label/`label_horizon_days` pairs satisfy the leak-free invariant (max forward Ref == label_horizon_days). The parametrized test asserts the label string `Ref($close, -{fwd})/...` and `label_horizon_days == horizon` for (h1,2,2)/(h10,11,11)/(h20,21,21), matching the recipe files.
