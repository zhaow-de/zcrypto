# Funding-carry Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the iter-15 `$funding` panel into a feature — a `FundingRateProcessor` appending a focused 5-column carry set to the Alpha158 frame — plus two recipes (`funding_steady` isolation, `funding_crossasset_steady` stacking), so the funding-carry edge can be tested via the multi-seed holdout A/B.

**Architecture:** Mirror the iter-13 cross-asset pattern exactly: `cli/experiment/features/funding.py` holds a pure `funding_features(wide_panel) -> (datetime, instrument) frame` (qlib-free, unit-testable) + a `FundingRateProcessor(Processor)` whose `__call__` loads the `$funding` wide panel via a thin `_load_funding` seam over `D.features`, computes the features, reindexes to the input frame's index, and appends each as a `("feature", <name>)` column. Two recipes copy `steady`/`crossasset_steady` verbatim and prepend the processor.

**Tech Stack:** Python 3.12, uv, pandas, qlib, pytest, ruff.

## Global Constraints

- **Reuse the cross-asset pattern; do not modify `cli/experiment/features/cross_asset.py`.** The funding module is a sibling that mirrors it (its own small `_stack` helper — a 4-line copy, to avoid a cross-module private import).
- **All funding features are leak-safe** — current/past funding or the same-day cross-section only (trailing `rolling`/`shift`; same-day `rank`). No forward `Ref`/negative shift. Guarded by a leak-safe test.
- **The recipes hold the base book constant.** `funding_steady` = `steady` verbatim except `name` + the prepended processor; `funding_crossasset_steady` = `crossasset_steady` verbatim except `name` + the added processor. `feature_config` stays `Alpha158`. A drift-guard test asserts the book matches the base recipe.
- **Processor wiring:** `FundingRateProcessor` is prepended to `infer_processors` **before** `RobustZScoreNorm` (so the appended columns get normalized). In the combo, order is `CrossAssetProcessor`, `FundingRateProcessor`, `RobustZScoreNorm`, `Fillna`.
- **Feature columns (5), exact names:** `funding_level`, `funding_z`, `funding_csrank`, `funding_ma`, `funding_chg`. Windows: `z_window=30`, `ma_window=7`, `chg_window=7`.
- ruff: line length 132, double quotes, import sorting (`select = ["I"]`). Run `uv run ruff check --fix <files>` + `uv run ruff format <files>` before each commit.
- Commit messages: `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: `funding.py` — feature function + processor

**Files:**
- Create: `cli/experiment/features/funding.py`
- Test: `tests/test_funding_feature.py`

**Interfaces:**
- Produces: `funding_features(funding: pd.DataFrame, *, z_window=30, ma_window=7, chg_window=7) -> pd.DataFrame` (MultiIndex `(datetime, instrument)`, columns the 5 names above); `_load_funding(insts, start, end) -> pd.DataFrame` (wide date×instrument `$funding` panel); `FundingRateProcessor(Processor)` (consumed by Task 2's recipes via `module_path="cli.experiment.features.funding"`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_funding_feature.py` (mirrors `tests/test_cross_asset.py`):

```python
import numpy as np
import pandas as pd

from cli.experiment.features.funding import funding_features

_COLS = {"funding_level", "funding_z", "funding_csrank", "funding_ma", "funding_chg"}


def _panel():
    idx = pd.date_range("2020-01-01", periods=120, freq="D")
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "BTCUSDT": rng.normal(0.0001, 0.0005, 120),
            "ETHUSDT": rng.normal(0.0002, 0.0006, 120),
            "XRPUSDT": rng.normal(-0.0001, 0.0004, 120),
        },
        index=idx,
    )


def test_expected_columns():
    f = funding_features(_panel())
    assert _COLS.issubset(set(f.columns))


def test_index_names():
    f = funding_features(_panel())
    assert f.index.names == ["datetime", "instrument"]


def test_csrank_in_unit_interval():
    f = funding_features(_panel())
    r = f["funding_csrank"].dropna()
    assert (r > 0).all() and (r <= 1.0).all()


def test_leak_safe_trailing():
    p = _panel()
    full = funding_features(p)
    truncated = funding_features(p.iloc[:100])
    t = p.index[99]
    a = full.xs(t, level="datetime").sort_index()
    b = truncated.xs(t, level="datetime").sort_index()
    pd.testing.assert_frame_equal(a, b, check_like=True)


def test_finite_after_warmup():
    f = funding_features(_panel())
    warm = f.xs(pd.Timestamp("2020-03-15"), level="datetime")  # day 74 > 30-day warmup
    assert np.all(np.isfinite(warm.values))


def test_no_inf():
    f = funding_features(_panel())
    assert not np.any(np.isinf(f.values))


def test_nan_funding_column_does_not_crash_or_inf():
    p = _panel()
    p["BTCEUR"] = np.nan  # a reference pair with no funding coverage
    f = funding_features(p)
    assert not np.any(np.isinf(f.values))
    # the NaN-funding instrument's level is NaN (resolved downstream by Fillna)
    assert f.xs("BTCEUR", level="instrument")["funding_level"].isna().all()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_funding_feature.py -v`
Expected: FAIL — `ModuleNotFoundError: cli.experiment.features.funding`.

- [ ] **Step 3: Implement `funding.py`**

```python
"""Pure funding-rate (carry) feature computation + a qlib Processor that appends it.

Mirrors cli/experiment/features/cross_asset.py: a qlib-free pure function over a wide
`$funding` panel, plus a Processor that loads the panel via D.features and appends the
features as ("feature", <name>) columns. Features capture the perpetual-funding carry that
OHLCV lacks: level (daily carry), extremity (z vs own history), relative crowding
(cross-sectional rank), persistent regime (rolling mean), and trend (change). All are
leak-safe — current/past funding or the same-day cross-section only.
"""

from __future__ import annotations

import pandas as pd
from qlib.data.dataset.processor import Processor


def _stack(wide: pd.DataFrame, col_name: str) -> pd.DataFrame:
    """Stack a wide (date × instrument) frame into a ("datetime","instrument") single-col frame.

    Mirrors cross_asset._stack; future_stack=True (pandas 2.1+) never silently drops NaN rows.
    """
    s = wide.stack(future_stack=True)
    s.index.names = ["datetime", "instrument"]
    return s.rename(col_name).to_frame()


def funding_features(
    funding: pd.DataFrame,
    *,
    z_window: int = 30,
    ma_window: int = 7,
    chg_window: int = 7,
) -> pd.DataFrame:
    """Map a wide daily-`$funding` panel (index=date, columns=instrument) to a
    (datetime, instrument) feature frame with the 5 focused carry columns.

    Leak-safe: every column uses only current/past funding (trailing rolling/shift) or the
    same-day cross-section (rank). Index names are exactly ("datetime", "instrument").
    """
    mean = funding.rolling(z_window).mean()
    std = funding.rolling(z_window).std()
    families = [
        _stack(funding, "funding_level"),
        _stack((funding - mean) / std, "funding_z"),
        _stack(funding.rank(axis=1, pct=True), "funding_csrank"),
        _stack(funding.rolling(ma_window).mean(), "funding_ma"),
        _stack(funding - funding.shift(chg_window), "funding_chg"),
    ]
    out = pd.concat(families, axis=1)
    out.index.names = ["datetime", "instrument"]
    return out


def _load_funding(insts, start, end) -> pd.DataFrame:
    """Load `$funding` for `insts` over [start, end] as a wide date × instrument panel.

    Thin seam over qlib's `D.features` so the processor can be tested without qlib init / redis.
    """
    from qlib.data import D

    s = D.features(list(insts), ["$funding"], start_time=start, end_time=end, freq="day")["$funding"]
    return s.unstack(level="instrument")


class FundingRateProcessor(Processor):
    """qlib `Processor` appending `funding_features` as `("feature", <name>)` columns.

    Wire it FIRST in a recipe's `infer_processors` so a later `RobustZScoreNorm` normalizes the
    appended features. `kwargs` are forwarded to `funding_features`.
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __call__(self, df: pd.DataFrame) -> pd.DataFrame:
        dt = df.index.get_level_values("datetime")
        insts = df.index.get_level_values("instrument").unique()
        funding = _load_funding(insts, dt.min(), dt.max())
        feats = funding_features(funding, **self.kwargs)
        feats = feats.reindex(df.index)
        for name in feats.columns:
            df[("feature", name)] = feats[name]
        return df
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_funding_feature.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Add a processor-wiring test**

Append to `tests/test_funding_feature.py` (tests the Processor appends columns, with `_load_funding` monkeypatched so no qlib/redis is needed):

```python
def test_processor_appends_feature_columns(monkeypatch):
    from cli.experiment.features import funding as fmod

    panel = _panel()
    monkeypatch.setattr(fmod, "_load_funding", lambda insts, start, end: panel)

    idx = pd.MultiIndex.from_product(
        [panel.index, ["BTCUSDT", "ETHUSDT", "XRPUSDT"]], names=["datetime", "instrument"]
    )
    df = pd.DataFrame({("feature", "EXISTING"): 0.0}, index=idx)

    out = fmod.FundingRateProcessor()(df)
    for name in _COLS:
        assert ("feature", name) in out.columns
    assert ("feature", "EXISTING") in out.columns  # original column preserved
```

- [ ] **Step 6: Run the wiring test**

Run: `uv run pytest tests/test_funding_feature.py::test_processor_appends_feature_columns -v`
Expected: PASS.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check --fix cli/experiment/features/funding.py tests/test_funding_feature.py
uv run ruff format cli/experiment/features/funding.py tests/test_funding_feature.py
git add cli/experiment/features/funding.py tests/test_funding_feature.py
git commit -m "feat(experiment): add FundingRateProcessor + funding carry features"
```

---

### Task 2: `funding_steady` + `funding_crossasset_steady` recipes + README

**Files:**
- Create: `cli/experiment/recipes/funding_steady.py`, `cli/experiment/recipes/funding_crossasset_steady.py`
- Modify: `README.md` (Usage — recipe list)
- Test: `tests/test_experiment_recipe.py`

**Interfaces:**
- Consumes: `FundingRateProcessor` (Task 1) via `module_path="cli.experiment.features.funding"`; the existing `steady` / `crossasset_steady` recipes as the base books.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_experiment_recipe.py`:

```python
def _infer_classes(recipe):
    return [p["class"] for p in recipe.handler_kwargs["infer_processors"]]


def test_funding_steady_wires_processor_and_matches_steady_book():
    import dataclasses

    from cli.experiment.recipes.base import resolve_recipe

    fs = resolve_recipe("funding_steady")
    steady = resolve_recipe("steady")
    # FundingRateProcessor is prepended first, before RobustZScoreNorm.
    assert _infer_classes(fs)[0] == "FundingRateProcessor"
    assert _infer_classes(fs)[1] == "RobustZScoreNorm"
    # Book matches steady except name + infer_processors (clean A/B isolation).
    assert dataclasses.replace(fs, name="steady", handler_kwargs=steady.handler_kwargs) == steady


def test_funding_crossasset_steady_stacks_both_processors():
    import dataclasses

    from cli.experiment.recipes.base import resolve_recipe

    fx = resolve_recipe("funding_crossasset_steady")
    base = resolve_recipe("crossasset_steady")
    classes = _infer_classes(fx)
    # Both feature processors precede the normalizer.
    assert classes[:2] == ["CrossAssetProcessor", "FundingRateProcessor"]
    assert classes[2] == "RobustZScoreNorm"
    assert dataclasses.replace(fx, name="crossasset_steady", handler_kwargs=base.handler_kwargs) == base
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_experiment_recipe.py -k "funding_steady or funding_crossasset" -v`
Expected: FAIL — `Recipe 'funding_steady' not found`.

- [ ] **Step 3: Create `funding_steady.py`**

Copy `cli/experiment/recipes/steady.py` verbatim to `cli/experiment/recipes/funding_steady.py`, then make exactly two changes: set `name="funding_steady"`, and prepend the `FundingRateProcessor` as the first `infer_processor`. The resulting `handler_kwargs["infer_processors"]` must be:

```python
        "infer_processors": [
            {"class": "FundingRateProcessor", "module_path": "cli.experiment.features.funding", "kwargs": {}},
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
```

Update the module docstring's first line to describe `funding_steady` (steady's book + the funding carry features prepended; the A/B isolates funding's contribution vs `steady`). Everything else (model_config, strategy_config, segments, universe, label, fees, cv knobs) is a verbatim copy of `steady`.

- [ ] **Step 4: Create `funding_crossasset_steady.py`**

Copy `cli/experiment/recipes/crossasset_steady.py` verbatim to `cli/experiment/recipes/funding_crossasset_steady.py`, then: set `name="funding_crossasset_steady"`, and insert `FundingRateProcessor` immediately after `CrossAssetProcessor` in `infer_processors`. The block must be:

```python
        "infer_processors": [
            {"class": "CrossAssetProcessor", "module_path": "cli.experiment.features.cross_asset", "kwargs": {}},
            {"class": "FundingRateProcessor", "module_path": "cli.experiment.features.funding", "kwargs": {}},
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
```

Update the module docstring's first line to describe `funding_crossasset_steady` (crossasset's book + funding features stacked; the A/B vs `crossasset_steady` tests whether funding stacks with cross-asset). Everything else is a verbatim copy of `crossasset_steady`.

- [ ] **Step 5: Run the recipe tests to verify they pass**

Run: `uv run pytest tests/test_experiment_recipe.py -k "funding_steady or funding_crossasset" -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Update README Usage**

In `README.md`, add `funding_steady` and `funding_crossasset_steady` to the `## Usage` recipe list (wherever the recipes — `steady`, `crossasset_steady`, etc. — are enumerated), each with a one-line description: `funding_steady` — steady's book + perp-funding carry features (the isolation A/B); `funding_crossasset_steady` — crossasset's book + funding features stacked. Don't hand-edit the mdformat TOC.

- [ ] **Step 7: Lint + targeted suite + commit**

```bash
uv run ruff check --fix cli/experiment/recipes/funding_steady.py cli/experiment/recipes/funding_crossasset_steady.py tests/test_experiment_recipe.py
uv run ruff format cli/experiment/recipes/funding_steady.py cli/experiment/recipes/funding_crossasset_steady.py tests/test_experiment_recipe.py
uv run pytest tests/test_experiment_recipe.py tests/test_funding_feature.py -q
git add cli/experiment/recipes/funding_steady.py cli/experiment/recipes/funding_crossasset_steady.py tests/test_experiment_recipe.py README.md
git commit -m "feat(experiment): add funding_steady + funding_crossasset_steady recipes"
```

Expected: the targeted suite passes.

---

## Closeout (operational — run by the orchestrator after Tasks 1-2 land, NOT a subagent task)

1. **Run the A/Bs** (redis up via `scripts/redis.sh start`), `--seeds 16 --deterministic --quick`, realistic-cost default:
   - `funding_steady` and `steady` → the funding-isolation A/B.
   - `funding_crossasset_steady` and `crossasset_steady` → the stacking A/B.
2. **Compute the verdict on the cost-adjusted Sharpe** (per `T0015`, NOT `ending_value` — the holdout `ending_value` is gross). Use the **paired per-seed** difference (funding-variant minus base, same seed) as the clean measure; report mean paired ΔSharpe vs the seed-noise band. Verdict: does funding add edge beyond OHLCV? does it stack with cross-asset?
3. **Advance `T0010`** (stays `partial`): update `## Done so far` (funding feature + recipes + verdict landed) and trim `## Suggested next steps` to the on-chain / order-book remainder. (No archive move — T0010 stays partial.)
4. **README `## Usage`:** confirm the two recipes are listed (Task 2).
5. **iter-20 iterations-history entry:** the feature, the two recipes, the funding-edge + stacking verdict.

---

## Self-Review

**Spec coverage:** Decision 1 (FundingRateProcessor mirroring cross_asset) → Task 1; Decision 2 (5 leak-safe features) → Task 1 (`funding_features` + the leak-safe / csrank / finite tests); Decision 3 (two recipes) → Task 2; Decision 4 (multi-seed A/B on cost-adjusted Sharpe) → Closeout 1-2; Decision 5 (NaN coverage) → Task 1 (`test_nan_funding_column_does_not_crash_or_inf` + downstream Fillna). README → Task 2. T0010 advance + iter-20 history → Closeout 3/5.

**Placeholder scan:** No TBD/TODO. All code steps carry full code; the recipes are "copy base verbatim + 2 changes" with the exact infer_processors block shown. The verdict values are correctly closeout (the A/B runs).

**Type consistency:** `funding_features(funding, *, z_window=30, ma_window=7, chg_window=7)` and the 5 column names (`funding_level`/`funding_z`/`funding_csrank`/`funding_ma`/`funding_chg`) identical across Task 1 code, Task 1 tests, and the spec. `FundingRateProcessor` + `module_path="cli.experiment.features.funding"` identical across Task 1 and Task 2's recipe blocks. `_load_funding`/`_stack` names consistent. The drift-guard tests use `dataclasses.replace(..., handler_kwargs=base.handler_kwargs)` to assert the book matches the base recipe.
