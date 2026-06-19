# Validation rigor: purged k-fold + embargo → CPCV — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `zcrypto experiment --recipe <name>` rigorous by default — run combinatorial purged cross-validation (CPCV) over `train+valid`, report a per-recipe out-of-sample Sharpe distribution (+ rank-IC), keep `test` as an untouched final holdout, and add `--quick` to opt back into today's single run.

**Architecture:** A pure split engine (`cli/experiment/cv.py`, no qlib) generates purged + embargoed combinatorial splits and stitches per-split predictions into φ backtest paths. An orchestrator (`cli/experiment/cpcv.py`) materializes the Alpha158 feature/label matrix once via the qlib handler, trains a LightGBM booster per split (fixed rounds, slices in pandas), predicts held-out rows, assembles paths, backtests each via qlib's signal-driven `backtest()`, and aggregates. The holdout step is today's `run_experiment`, unchanged. `command.py` runs CPCV then holdout by default (or holdout-only under `--quick`), writing `cv_results.json` + a 4th report panel.

**Tech Stack:** Python 3.12, uv, qlib (`pyqlib`), LightGBM, pandas, plotly, Typer; pytest + Typer `CliRunner`.

**Spec:** `docs/specs/00008-validation-rigor-cpcv-design.md`. **Branch:** `feat/validation-rigor-cpcv`.

**Key facts validated against the installed qlib (0.9.x):**
- `qlib.backtest.backtest(start_time, end_time, strategy, executor, benchmark, account, exchange_kwargs, pos_type="Position") -> (portfolio_metric_dict, indicator_dict)`; `portfolio_metric_dict["1day"] == (report_df, positions_dict)`; `report_df` has columns `return`, `bench`, `cost`.
- `TopkDropoutStrategy(*, signal, topk, n_drop, ...)` accepts `signal` as a `pd.Series` indexed by `(datetime, instrument)`.
- `risk_analysis(r: pd.Series, freq="day") -> DataFrame` indexed by metric names (`annualized_return`, `information_ratio`, `max_drawdown`, …), single column; access `df.loc[metric].iloc[0]`. **"Sharpe" = `information_ratio` of absolute (cost-adjusted) returns** (rf = 0), matching `scaffold._extract_metrics`'s `strategy_absolute`.
- `DatasetH.prepare(segments, col_set, data_key)` with `DataHandlerLP.DK_L` (learn: normalized features + per-day-normalized label, NaN-label rows dropped) and `DataHandlerLP.DK_I` (infer: normalized features, label not dropped); `CS_ALL` returns all columns. LightGBM is invariant to the monotonic feature scaling, so a single global materialization is fine for this tree recipe (the primary label-overlap leakage is removed by purge/embargo).

---

## File structure

| File | Responsibility | Task |
| --- | --- | --- |
| `cli/experiment/recipes/base.py` | + 4 CV fields on `Recipe` | 1 |
| `cli/experiment/cv.py` (new) | Pure split math: groups, C(N,k) splits, purge/embargo, path assembly | 2 |
| `cli/experiment/scaffold.py` | Extract `exchange_kwargs(recipe)`; holdout flow unchanged | 3 |
| `cli/experiment/cpcv.py` (new) | qlib orchestration: materialize → per-split fit/predict → assemble → per-path backtest → aggregate | 4 |
| `cli/experiment/report.py` | + optional 4th CV-distribution panel | 5 |
| `cli/experiment/command.py` | Default CPCV→holdout; `--quick`; `cv_results.json`; CV stdout line | 6 |
| `tests/test_experiment_*.py` | Move single-run tests to `--quick` (suite speed) | 7 |
| `.claude/rules/open-topics.md`, `docs/open-topics/...`, `docs/iterations-history.md` | Closeout | 8 |

Each task ends by running the gate: `uv run ruff check && uv run ruff format --check && uv run pytest -q` (redis-gated tests skip when redis is down; start it with `scripts/redis.sh start`). Commit only on green.

---

## Task 1: Recipe CV fields

**Files:**
- Modify: `cli/experiment/recipes/base.py` (the `Recipe` dataclass, after `fee_preset`)
- Test: `tests/test_experiment_recipe.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_experiment_recipe.py`:

```python
def test_recipe_has_cv_defaults():
    from cli.experiment.recipes.base import Recipe
    from cli.experiment.recipes import skeleton

    r = skeleton.RECIPE
    assert r.label_horizon_days == 2
    assert r.feature_lookback_days == 60
    assert r.cv_n_groups == 6
    assert r.cv_test_groups == 2
    # configurable
    assert Recipe(
        name="x", handler_kwargs={}, model_config={}, strategy_kwargs={},
        segments={}, universe=(), reference_instruments=(),
        cv_n_groups=4, cv_test_groups=2,
    ).cv_n_groups == 4
```

- [ ] **Step 2: Run it, expect FAIL** — `uv run pytest tests/test_experiment_recipe.py::test_recipe_has_cv_defaults -v` → `AttributeError`/`TypeError` (fields don't exist).

- [ ] **Step 3: Add the fields** — in `cli/experiment/recipes/base.py`, inside `class Recipe`, immediately after the `fee_preset: str = field(default="vip2_bnb")` line:

```python
    # CPCV / purge-embargo knobs (see docs/specs/00008). Defaults match Alpha158's
    # default label horizon and longest feature window; behavior-preserving.
    label_horizon_days: int = field(default=2)
    feature_lookback_days: int = field(default=60)
    cv_n_groups: int = field(default=6)
    cv_test_groups: int = field(default=2)
```

- [ ] **Step 4: Run it, expect PASS** — `uv run pytest tests/test_experiment_recipe.py -v`.

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add cli/experiment/recipes/base.py tests/test_experiment_recipe.py
git commit -m "feat(experiment): add CPCV knobs to the Recipe dataclass"
```

---

## Task 2: Pure CPCV split engine (`cv.py`)

**Files:**
- Create: `cli/experiment/cv.py`
- Test: `tests/test_cv.py` (new)

Operates on an ordered calendar **by index position**. The crypto calendar is 24/7 daily and contiguous, so one position == one day; `purge_days`/`embargo_days` are position counts.

- [ ] **Step 1: Write the failing tests** — create `tests/test_cv.py`:

```python
from math import comb

import pandas as pd

from cli.experiment.cv import assemble_paths, build_cv_plan


def _blocks(sorted_positions):
    out, start, prev = [], None, None
    for p in sorted_positions:
        if start is None:
            start = prev = p
        elif p == prev + 1:
            prev = p
        else:
            out.append((start, prev + 1))
            start = prev = p
    if start is not None:
        out.append((start, prev + 1))
    return out


def test_split_and_path_counts():
    plan = build_cv_plan(list(range(60)), n_groups=6, test_groups=2, purge_days=0, embargo_days=0)
    assert len(plan.splits) == comb(6, 2) == 15
    assert plan.n_paths == comb(5, 1) == 5


def test_groups_partition_calendar_contiguously():
    plan = build_cv_plan(list(range(60)), n_groups=6, test_groups=2, purge_days=0, embargo_days=0)
    assert [d for g in plan.groups for d in g] == list(range(60))


def test_purge_and_embargo_clear_train_around_each_test_block():
    purge, embargo = 3, 5
    plan = build_cv_plan(list(range(60)), n_groups=6, test_groups=2, purge_days=purge, embargo_days=embargo)
    for split in plan.splits:
        train = set(split.train_dates)
        assert not (train & set(split.test_dates))  # disjoint
        forbidden = set()
        for s, e in _blocks(sorted(split.test_dates)):
            forbidden |= set(range(s - purge, s)) | set(range(e, e + embargo))
        assert not (train & forbidden)


def test_invalid_params_raise():
    import pytest

    with pytest.raises(ValueError):
        build_cv_plan(list(range(60)), n_groups=6, test_groups=6, purge_days=0, embargo_days=0)
    with pytest.raises(ValueError):
        build_cv_plan(list(range(3)), n_groups=6, test_groups=2, purge_days=0, embargo_days=0)


def test_assemble_paths_full_coverage_and_provenance():
    cal = list(pd.date_range("2020-01-01", periods=60, freq="D"))
    plan = build_cv_plan(cal, n_groups=6, test_groups=2, purge_days=0, embargo_days=0)
    # fake predictions: for split i, a Series over its test dates × 2 instruments,
    # value encodes the split index so we can trace provenance.
    preds = {}
    for i, split in enumerate(plan.splits):
        idx = pd.MultiIndex.from_product([split.test_dates, ["A", "B"]], names=["datetime", "instrument"])
        preds[i] = pd.Series(float(i), index=idx)
    paths = assemble_paths(plan, preds)
    assert len(paths) == plan.n_paths
    for path in paths:
        dates = path.index.get_level_values(0).unique()
        assert len(dates) == 60  # full span, every date once
        assert path.index.is_monotonic_increasing
```

- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/test_cv.py -v` → `ModuleNotFoundError: cli.experiment.cv`.

- [ ] **Step 3: Implement `cli/experiment/cv.py`**:

```python
"""Pure combinatorial purged cross-validation (CPCV) split math — no qlib.

Works on an ordered calendar by INDEX position. The crypto calendar is 24/7
daily and contiguous, so one position == one day; `purge_days` / `embargo_days`
are therefore position counts.

References: López de Prado, *Advances in Financial Machine Learning*, Ch. 7
(purged k-fold + embargo) and Ch. 12 (CPCV, backtest paths).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import comb


@dataclass(frozen=True)
class CVSplit:
    test_group_ids: tuple  # group indices forming the test set
    train_dates: list  # calendar dates used for training (purged + embargoed)
    test_dates: list  # calendar dates in the test groups


@dataclass(frozen=True)
class CVPlan:
    n_groups: int
    test_groups: int
    purge_days: int
    embargo_days: int
    groups: list  # list[list[date]] — each group's dates in calendar order
    splits: list  # list[CVSplit], length C(n_groups, test_groups)

    @property
    def n_paths(self) -> int:
        return comb(self.n_groups - 1, self.test_groups - 1)


def _group_index_bounds(n_dates: int, n_groups: int) -> list[tuple[int, int]]:
    if n_groups < 2:
        raise ValueError(f"n_groups must be >= 2, got {n_groups}")
    if n_dates < n_groups:
        raise ValueError(f"calendar too short ({n_dates} dates) for {n_groups} groups")
    base, extra = divmod(n_dates, n_groups)
    bounds, start = [], 0
    for g in range(n_groups):
        size = base + (1 if g < extra else 0)
        bounds.append((start, start + size))
        start += size
    return bounds


def _contiguous_blocks(sorted_positions):
    """Yield (start, end) half-open index ranges of maximal contiguous runs."""
    if not sorted_positions:
        return
    start = prev = sorted_positions[0]
    for p in sorted_positions[1:]:
        if p == prev + 1:
            prev = p
            continue
        yield (start, prev + 1)
        start = prev = p
    yield (start, prev + 1)


def build_cv_plan(calendar, *, n_groups: int, test_groups: int, purge_days: int, embargo_days: int) -> CVPlan:
    if not 1 <= test_groups < n_groups:
        raise ValueError(f"test_groups must be in [1, n_groups), got {test_groups} (n_groups={n_groups})")
    cal = list(calendar)
    n = len(cal)
    bounds = _group_index_bounds(n, n_groups)
    groups = [cal[s:e] for (s, e) in bounds]

    splits = []
    for test_ids in combinations(range(n_groups), test_groups):
        test_pos = set()
        for gid in test_ids:
            s, e = bounds[gid]
            test_pos.update(range(s, e))
        train_pos = set(range(n)) - test_pos
        for s, e in _contiguous_blocks(sorted(test_pos)):
            for p in range(max(0, s - purge_days), s):  # purge: leading edge
                train_pos.discard(p)
            for p in range(e, min(n, e + embargo_days)):  # embargo: trailing edge
                train_pos.discard(p)
        splits.append(
            CVSplit(
                test_group_ids=test_ids,
                train_dates=[cal[i] for i in sorted(train_pos)],
                test_dates=[cal[i] for i in sorted(test_pos)],
            )
        )

    return CVPlan(
        n_groups=n_groups,
        test_groups=test_groups,
        purge_days=purge_days,
        embargo_days=embargo_days,
        groups=groups,
        splits=splits,
    )


def assemble_paths(plan: CVPlan, predictions: dict):
    """Stitch per-split test predictions into ``plan.n_paths`` full-span path Series.

    ``predictions``: ``{split_index -> pd.Series}`` indexed by ``(datetime,
    instrument)`` over that split's ``test_dates``. Returns ``list[pd.Series]``,
    each spanning the full calendar (every date once), sorted by index.

    Path ``j`` takes, for every group, that group's slice from the ``j``-th split
    in which the group is a test group — so each (group, split) test cell is used
    exactly once across all paths.
    """
    import pandas as pd

    group_to_splits = {g: [] for g in range(plan.n_groups)}
    for si, split in enumerate(plan.splits):
        for gid in split.test_group_ids:
            group_to_splits[gid].append(si)

    paths = []
    for j in range(plan.n_paths):
        pieces = []
        for gid in range(plan.n_groups):
            si = group_to_splits[gid][j]
            group_dates = set(plan.groups[gid])
            pred = predictions[si]
            mask = pred.index.get_level_values(0).isin(group_dates)
            pieces.append(pred[mask])
        paths.append(pd.concat(pieces).sort_index())
    return paths
```

- [ ] **Step 4: Run, expect PASS** — `uv run pytest tests/test_cv.py -v`.

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add cli/experiment/cv.py tests/test_cv.py
git commit -m "feat(experiment): add pure CPCV split engine (purge/embargo/path assembly)"
```

---

## Task 3: Extract the shared exchange-kwargs builder (`scaffold.py`)

So `cpcv.py` and the holdout share one fee/`trade_unit` source. **Pure refactor — behavior and all existing tests unchanged.**

**Files:**
- Modify: `cli/experiment/scaffold.py` (`_port_analysis_config`, lines ~89–120)

- [ ] **Step 1: Add the helper** — in `cli/experiment/scaffold.py`, just above `def _port_analysis_config(`:

```python
def exchange_kwargs(recipe: Recipe) -> dict:
    """Shared exchange config for both the holdout backtest and CPCV path backtests.

    `trade_unit=None` enables fractional crypto fills (a $10k account cannot buy
    whole-unit BTC/ETH; see the comment in `_port_analysis_config`).
    """
    fee_open, fee_close = FEE_PRESETS[recipe.fee_preset]
    return {
        "freq": "day",
        "deal_price": "close",
        "open_cost": fee_open,
        "close_cost": fee_close,
        "min_cost": 0,
        "trade_unit": None,
    }
```

- [ ] **Step 2: Use it in `_port_analysis_config`** — replace the body of `_port_analysis_config` so the `exchange_kwargs` key reuses the helper. The function becomes:

```python
def _port_analysis_config(recipe: Recipe, model, dataset) -> dict:
    return {
        "executor": {
            "class": "SimulatorExecutor",
            "module_path": "qlib.backtest.executor",
            "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True},
        },
        "strategy": {
            "class": "TopkDropoutStrategy",
            "module_path": "qlib.contrib.strategy.signal_strategy",
            "kwargs": {**recipe.strategy_kwargs, "signal": (model, dataset)},
        },
        "backtest": {
            "start_time": recipe.segments["test"][0],
            "end_time": recipe.segments["test"][1],
            "account": recipe.account,
            "benchmark": recipe.benchmark,
            "exchange_kwargs": exchange_kwargs(recipe),
        },
    }
```

(The long `trade_unit` comment moves into `exchange_kwargs`; the FEE_PRESETS import is already present.)

- [ ] **Step 3: Run the existing scaffold/e2e tests, expect PASS (unchanged behavior)**

```bash
uv run pytest tests/test_experiment_scaffold.py -q
scripts/redis.sh start  # if not already up
uv run pytest tests/test_experiment_command.py -q
```

- [ ] **Step 4: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add cli/experiment/scaffold.py
git commit -m "refactor(experiment): extract shared exchange_kwargs from scaffold"
```

---

## Task 4: CPCV orchestration (`cpcv.py`)

**Files:**
- Create: `cli/experiment/cpcv.py`
- Test: `tests/test_experiment_cpcv.py` (new, redis-gated)

`run_cpcv` runs its own lean qlib session (no MLflow/recorder needed — it uses the signal-driven `backtest()`), reusing the on-disk cache via `ensure_cache_fresh`. It returns a `CPCVResult`.

- [ ] **Step 1: Write the failing test** — create `tests/test_experiment_cpcv.py`:

```python
from __future__ import annotations

import dataclasses
import shutil
from importlib.resources import as_file, files

import pytest


def _redis_up() -> bool:
    try:
        import redis

        redis.Redis(host="localhost", port=6379, socket_connect_timeout=2).ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _redis_up(), reason="needs redis (scripts/redis.sh start)")
def test_run_cpcv_returns_distribution(tmp_path):
    from cli.experiment.cpcv import CPCVResult, run_cpcv
    from cli.experiment.recipes import skeleton

    fixture_ref = files("cli.experiment").joinpath("data", "provider")
    data_dir = tmp_path / "provider"
    with as_file(fixture_ref) as src:
        shutil.copytree(src, data_dir)

    # Scaled CV config that fits the fixture span (2023-01-02 .. 2024-06-28).
    recipe = dataclasses.replace(
        skeleton.RECIPE,
        segments={
            "train": ("2023-03-01", "2023-12-31"),
            "valid": ("2024-01-01", "2024-02-29"),
            "test": ("2024-03-01", "2024-06-27"),
        },
        feature_lookback_days=5,
        label_horizon_days=2,
        cv_n_groups=4,
        cv_test_groups=2,
    )

    result = run_cpcv(recipe, data_dir=data_dir, out_dir=tmp_path / "runs", refresh_cache=True)

    assert isinstance(result, CPCVResult)
    assert result.meta["n_splits"] == 6  # C(4,2)
    assert result.meta["n_paths"] == 3  # C(3,1)
    assert len(result.paths) == 3
    for p in result.paths:
        assert {"path", "sharpe", "annualized_return", "max_drawdown"} <= set(p)
        assert isinstance(p["sharpe"], float)
    assert {"sharpe_mean", "sharpe_std", "sharpe_median", "sharpe_worst"} <= set(result.distribution)
    assert {"mean", "std", "ir"} <= set(result.rank_ic)
```

- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/test_experiment_cpcv.py -v` → `ModuleNotFoundError: cli.experiment.cpcv`.

- [ ] **Step 3: Implement `cli/experiment/cpcv.py`**. The numbered comments map to spec §"qlib integration". **Verify against live qlib while implementing** — if a `report_df` column or `backtest()` return shape differs, adapt (the test is the oracle):

```python
"""Combinatorial purged cross-validation (CPCV) orchestration for the experiment.

Materializes the Alpha158 feature/label matrix once, trains a LightGBM booster
per purged+embargoed split, predicts the held-out rows, stitches predictions into
backtest paths (cli.experiment.cv), backtests each path via qlib's signal-driven
`backtest()`, and aggregates a Sharpe distribution (+ rank-IC).

The holdout run is `scaffold.run_experiment` (unchanged); this module is the CV
layer that runs before it. It uses no MLflow recorder.
"""

from __future__ import annotations

import contextlib
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from cli.experiment.cache import ensure_cache_fresh
from cli.experiment.cv import assemble_paths, build_cv_plan
from cli.experiment.recipes.base import Recipe
from cli.experiment.scaffold import _redis_preflight, exchange_kwargs
from cli.logging import get_logger

logger = get_logger("experiment.cpcv")

_METRICS = ["annualized_return", "information_ratio", "max_drawdown"]


@dataclass
class CPCVResult:
    meta: dict  # n_groups, test_groups, n_splits, n_paths, purge_days, embargo_days, span
    paths: list  # [{"path": i, "sharpe": .., "annualized_return": .., "max_drawdown": ..}]
    distribution: dict  # sharpe_mean / sharpe_std / sharpe_median / sharpe_worst
    rank_ic: dict  # mean / std / ir


def _lgb_params(recipe: Recipe) -> tuple[dict, int]:
    """Translate the recipe's LGBModel config into raw lightgbm params + num_boost_round.

    Mirrors qlib.contrib.model.gbdt.LGBModel.__init__: loss -> objective, verbosity
    -1, the rest forwarded; num_boost_round / early_stopping_rounds are pulled out
    (early stopping is intentionally disabled inside CV folds — fixed rounds).
    """
    kw = dict(recipe.model_config.get("kwargs", {}))
    num_boost_round = int(kw.pop("num_boost_round", 1000))
    kw.pop("early_stopping_rounds", None)
    loss = kw.pop("loss", "mse")
    params = {"objective": loss, "verbosity": -1, **kw}
    return params, num_boost_round


def _materialize(recipe: Recipe):
    """Return (infer_df, learn_df) over train+valid, MultiIndex (datetime, instrument).

    infer_df (DK_I): normalized features + label, no dropna — used for prediction.
    learn_df (DK_L): normalized features + per-day-normalized label, NaN-label rows
    dropped — used for training and rank-IC.
    """
    from qlib.data.dataset import DatasetH
    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.utils import init_instance_by_config

    cv_start = recipe.segments["train"][0]
    cv_end = recipe.segments["valid"][1]
    handler_kwargs = {
        **recipe.handler_kwargs,
        "instruments": list(recipe.universe),
        "start_time": cv_start,
        "end_time": cv_end,
        "fit_start_time": cv_start,
        "fit_end_time": cv_end,
        "freq": "day",
    }
    dataset = init_instance_by_config(
        {
            "class": "DatasetH",
            "module_path": "qlib.data.dataset",
            "kwargs": {
                "handler": {
                    "class": "Alpha158",
                    "module_path": "qlib.contrib.data.handler",
                    "kwargs": handler_kwargs,
                },
                "segments": {"all": (cv_start, cv_end)},
            },
        }
    )
    infer_df = dataset.prepare(segments="all", col_set=DataHandlerLP.CS_ALL, data_key=DataHandlerLP.DK_I)
    learn_df = dataset.prepare(segments="all", col_set=DataHandlerLP.CS_ALL, data_key=DataHandlerLP.DK_L)
    return infer_df, learn_df


def _split_xy(df: pd.DataFrame):
    """Split a CS_ALL frame into (feature DataFrame, label Series). label col = ('label','LABEL0')."""
    feat = df["feature"]
    label = df["label"].iloc[:, 0]
    return feat, label


def _rows_on(df: pd.DataFrame, dates: set):
    return df[df.index.get_level_values(0).isin(dates)]


def _rank_ic(pred: pd.Series, label: pd.Series) -> float:
    """Mean per-day Spearman rank correlation of pred vs label (NaN-safe)."""
    joined = pd.DataFrame({"p": pred, "y": label}).dropna()
    if joined.empty:
        return float("nan")
    daily = joined.groupby(level=0).apply(lambda g: g["p"].corr(g["y"], method="spearman") if len(g) > 1 else float("nan"))
    return float(daily.mean())


def run_cpcv(recipe: Recipe, *, data_dir: Path, out_dir: Path, refresh_cache: bool = False) -> CPCVResult:
    import lightgbm as lgb
    import qlib
    from qlib.backtest import backtest
    from qlib.constant import REG_US
    from qlib.contrib.evaluate import risk_analysis

    data_dir = Path(data_dir).resolve()
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    _redis_preflight()
    ensure_cache_fresh(data_dir, refresh=refresh_cache)
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

    with tempfile.TemporaryDirectory(prefix="zcrypto-cpcv-cwd-") as cwd_tmp, contextlib.chdir(cwd_tmp):
        qlib.init(
            provider_uri=str(data_dir),
            region=REG_US,
            expression_cache="DiskExpressionCache",
            dataset_cache="DiskDatasetCache",
            logging_config=None,
        )
        logger.info("cpcv-init", extra={"provider_uri": str(data_dir)})

        infer_df, learn_df = _materialize(recipe)
        infer_feat, _ = _split_xy(infer_df)
        learn_feat, learn_label = _split_xy(learn_df)

        calendar = sorted(infer_feat.index.get_level_values(0).unique())
        plan = build_cv_plan(
            calendar,
            n_groups=recipe.cv_n_groups,
            test_groups=recipe.cv_test_groups,
            purge_days=recipe.label_horizon_days,
            embargo_days=recipe.feature_lookback_days,
        )
        logger.info("cpcv-start", extra={"n_splits": len(plan.splits), "n_paths": plan.n_paths})

        params, num_boost_round = _lgb_params(recipe)
        predictions: dict = {}
        ic_values: list = []
        for i, split in enumerate(plan.splits):
            train_dates, test_dates = set(split.train_dates), set(split.test_dates)
            x_tr = _rows_on(learn_feat, train_dates)
            y_tr = _rows_on(learn_label, train_dates)
            booster = lgb.train(params, lgb.Dataset(x_tr.values, label=y_tr.values), num_boost_round=num_boost_round)

            x_te = _rows_on(infer_feat, test_dates)
            pred = pd.Series(booster.predict(x_te.values), index=x_te.index)
            predictions[i] = pred
            ic_values.append(_rank_ic(pred, _rows_on(learn_label, test_dates)))
            logger.info("split-trained", extra={"split": i, "n_train": len(x_tr), "n_test": len(x_te)})

        paths_pred = assemble_paths(plan, predictions)
        logger.info("paths-assembled", extra={"n_paths": len(paths_pred)})

        path_rows = []
        for j, signal in enumerate(paths_pred):
            dates = signal.index.get_level_values(0)
            pmd, _ = backtest(
                start_time=dates.min(),
                end_time=dates.max(),
                strategy={
                    "class": "TopkDropoutStrategy",
                    "module_path": "qlib.contrib.strategy.signal_strategy",
                    "kwargs": {**recipe.strategy_kwargs, "signal": signal},
                },
                executor={
                    "class": "SimulatorExecutor",
                    "module_path": "qlib.backtest.executor",
                    "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True},
                },
                benchmark=recipe.benchmark,
                account=recipe.account,
                exchange_kwargs=exchange_kwargs(recipe),
            )
            report_df = pmd["1day"][0]
            ra = risk_analysis(report_df["return"] - report_df["cost"], freq="day")
            m = {k: float(ra.loc[k].iloc[0]) for k in _METRICS}
            path_rows.append(
                {"path": j, "sharpe": m["information_ratio"], "annualized_return": m["annualized_return"], "max_drawdown": m["max_drawdown"]}
            )
            logger.info("path-backtest", extra={"path": j, "sharpe": m["information_ratio"]})

    sharpes = [r["sharpe"] for r in path_rows]
    ics = pd.Series([v for v in ic_values if not math.isnan(v)], dtype="float64")
    distribution = {
        "sharpe_mean": float(pd.Series(sharpes).mean()),
        "sharpe_std": float(pd.Series(sharpes).std()),
        "sharpe_median": float(pd.Series(sharpes).median()),
        "sharpe_worst": float(min(sharpes)),
    }
    rank_ic = {
        "mean": float(ics.mean()) if not ics.empty else float("nan"),
        "std": float(ics.std()) if not ics.empty else float("nan"),
        "ir": float(ics.mean() / ics.std()) if len(ics) > 1 and ics.std() else float("nan"),
    }
    meta = {
        "method": "CPCV",
        "n_groups": plan.n_groups,
        "test_groups": plan.test_groups,
        "n_splits": len(plan.splits),
        "n_paths": plan.n_paths,
        "purge_days": plan.purge_days,
        "embargo_days": plan.embargo_days,
        "span": [str(calendar[0]), str(calendar[-1])],
    }
    logger.info("cv-aggregated", extra={"distribution": distribution, "rank_ic": rank_ic})
    return CPCVResult(meta=meta, paths=path_rows, distribution=distribution, rank_ic=rank_ic)
```

> **Implementer notes / likely adjustments (verify with the redis-gated test):**
> - `_split_xy` assumes top-level column groups `feature`/`label` (qlib's `CS_ALL` MultiIndex columns). If `df["label"]` is already 1-D, use `df["label"]` directly.
> - `backtest()` may return the report under a key other than `"1day"` if qlib formats the freq differently — if `KeyError`, inspect `pmd.keys()` and pick the daily key (`next(iter(pmd))` is a safe fallback for a single daily frequency).
> - `groupby(level=0).apply(...)` on newer pandas may warn; if so, pass `include_groups=False` or compute IC with an explicit loop. Keep it NaN-safe.
> - If a path's backtest yields a degenerate (all-NaN) return series for the tiny fixture, the test only asserts floats exist and shapes — not numeric ranges — so NaNs are acceptable there; do **not** loosen the production code to mask real errors.

- [ ] **Step 4: Run, expect PASS** — `scripts/redis.sh start` then `uv run pytest tests/test_experiment_cpcv.py -v` (~minute on the fixture). Debug against the live API until green.

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add cli/experiment/cpcv.py tests/test_experiment_cpcv.py
git commit -m "feat(experiment): add CPCV orchestration (materialize, per-split fit, path backtests)"
```

---

## Task 5: CV-distribution report panel (`report.py`)

**Files:**
- Modify: `cli/experiment/report.py` (`build_report`)
- Test: `tests/test_experiment_report.py`

Add an optional `cv` argument; when given, render a 4th panel (histogram of path Sharpes + a vertical line at the holdout Sharpe). Decoupled from `CPCVResult` — `cv` is a plain dict so the panel is unit-testable without qlib.

- [ ] **Step 1: Write the failing test** — append to `tests/test_experiment_report.py`:

```python
def test_build_report_adds_cv_panel():
    import types

    import pandas as pd

    from cli.experiment.report import build_report

    idx = pd.date_range("2020-01-01", periods=5, freq="D")
    result = types.SimpleNamespace(
        recipe=types.SimpleNamespace(name="t", account=10000.0),
        account_curve=pd.Series(range(5), index=idx, dtype="float64"),
        benchmark_curve=pd.Series(range(5), index=idx, dtype="float64"),
        positions={},
        context_prices={},
    )
    cv = {"path_sharpes": [0.2, 0.5, 0.8], "holdout_sharpe": 0.6}
    fig = build_report(result, cv=cv)
    # 4 rows now (vs 3); the CV histogram trace is present.
    assert any(getattr(t, "type", None) == "histogram" for t in fig.data)
    fig_none = build_report(result)  # backward compatible: still 3 panels, no histogram
    assert not any(getattr(t, "type", None) == "histogram" for t in fig_none.data)
```

- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/test_experiment_report.py::test_build_report_adds_cv_panel -v`.

- [ ] **Step 3: Modify `build_report`** in `cli/experiment/report.py`:

3a. Change the signature line `def build_report(result, *, stress_windows=None) -> go.Figure:` to:

```python
def build_report(result, *, stress_windows=None, cv=None) -> go.Figure:
```

3b. Replace the `make_subplots(...)` call with a row-count that grows when `cv` is present:

```python
    n_rows = 4 if cv else 3
    titles = ["Equity (test window)", "Trade timeline", "Market context (rebased)"]
    if cv:
        titles.append("CPCV out-of-sample Sharpe distribution")
    fig = make_subplots(rows=n_rows, cols=1, subplot_titles=tuple(titles), vertical_spacing=0.06)
```

3c. Immediately before `fig.update_layout(...)` at the end, add the 4th-panel block:

```python
    # ------------------------------------------------------------------
    # Panel 4 — CPCV Sharpe distribution (only when cv results are provided)
    # ------------------------------------------------------------------
    if cv:
        sharpes = list(cv["path_sharpes"])
        fig.add_trace(
            go.Histogram(x=sharpes, name="path Sharpe", showlegend=False, marker={"color": "steelblue"}),
            row=4,
            col=1,
        )
        fig.add_vline(
            x=cv["holdout_sharpe"],
            line={"color": _SELL_COLOR, "width": 2, "dash": "dash"},
            annotation_text="holdout",
            annotation_position="top",
            row=4,
            col=1,
        )
```

3d. Change the height in `fig.update_layout(...)` so 4 rows fit:

```python
    fig.update_layout(title=title, height=300 * n_rows, template="plotly_white")
```

- [ ] **Step 4: Run, expect PASS** — `uv run pytest tests/test_experiment_report.py -v`.

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add cli/experiment/report.py tests/test_experiment_report.py
git commit -m "feat(experiment): add CPCV Sharpe-distribution report panel"
```

---

## Task 6: Command wiring — CPCV by default, `--quick`, `cv_results.json` (`command.py`)

**Files:**
- Modify: `cli/experiment/command.py`
- Modify: `README.md` (`## Usage` → experiment section; same change as the CLI per `readme-usage.md`)
- Test: `tests/test_experiment_command.py`

- [ ] **Step 1: Write the tests** — append to `tests/test_experiment_command.py` (the `_redis_up`, `runner`, imports already exist):

```python
@pytest.mark.skipif(not _redis_up(), reason="needs redis (scripts/redis.sh start)")
def test_experiment_quick_matches_single_run(tmp_path, monkeypatch):
    fixture_ref = files("cli.experiment").joinpath("data", "provider")
    data_dir = tmp_path / "provider"
    with as_file(fixture_ref) as src:
        shutil.copytree(src, data_dir)
    from cli.experiment.recipes import skeleton

    short = dataclasses.replace(
        skeleton.RECIPE,
        segments={
            "train": ("2023-03-01", "2023-12-31"),
            "valid": ("2024-01-01", "2024-02-29"),
            "test": ("2024-03-01", "2024-06-27"),
        },
    )
    monkeypatch.setattr("cli.experiment.command.resolve_recipe", lambda name: short)
    out_dir = tmp_path / "runs"
    result = runner.invoke(
        app,
        ["experiment", "--recipe", "skeleton", "--data-dir", str(data_dir), "--out", str(out_dir), "--no-open", "--refresh-cache", "--quick"],
    )
    assert result.exit_code == 0, result.output
    bundle = next(iter((out_dir / "skeleton").glob("*")))
    assert not (bundle / "cv_results.json").exists()  # --quick skips CPCV
    assert "CPCV" not in result.output


@pytest.mark.skipif(not _redis_up(), reason="needs redis (scripts/redis.sh start)")
def test_experiment_default_writes_cv_results(tmp_path, monkeypatch):
    fixture_ref = files("cli.experiment").joinpath("data", "provider")
    data_dir = tmp_path / "provider"
    with as_file(fixture_ref) as src:
        shutil.copytree(src, data_dir)
    from cli.experiment.recipes import skeleton

    short = dataclasses.replace(
        skeleton.RECIPE,
        segments={
            "train": ("2023-03-01", "2023-12-31"),
            "valid": ("2024-01-01", "2024-02-29"),
            "test": ("2024-03-01", "2024-06-27"),
        },
        feature_lookback_days=5,
        cv_n_groups=4,
        cv_test_groups=2,
    )
    monkeypatch.setattr("cli.experiment.command.resolve_recipe", lambda name: short)
    out_dir = tmp_path / "runs"
    result = runner.invoke(
        app,
        ["experiment", "--recipe", "skeleton", "--data-dir", str(data_dir), "--out", str(out_dir), "--no-open", "--refresh-cache"],
    )
    assert result.exit_code == 0, result.output
    bundle = next(iter((out_dir / "skeleton").glob("*")))
    cv = json.loads((bundle / "cv_results.json").read_text())
    assert cv["cv"]["n_paths"] == 3
    assert len(cv["paths"]) == 3
    assert "CPCV" in result.output
```

- [ ] **Step 2: Run, expect FAIL** — `scripts/redis.sh start` then `uv run pytest tests/test_experiment_command.py -k "quick or cv_results" -v`.

- [ ] **Step 3: Wire the command.** In `cli/experiment/command.py`:

3a. Add a `--quick` option. Inside `def experiment(`, after the `refresh_cache` option and before `open_report`:

```python
    quick: bool = typer.Option(
        False,
        "--quick/--no-quick",
        help="Skip CPCV; run only the single train→backtest holdout (today's fast path).",
    ),
```

3b. Run CPCV before the holdout and write `cv_results.json`. The current body builds `bundle`, calls `run_experiment`, then writes artifacts. Insert the CPCV block **after** `bundle.mkdir(...)` and **before** `from cli.experiment.scaffold import run_experiment` / `result = run_experiment(...)`:

```python
    cv_result = None
    if not quick:
        from cli.experiment.cpcv import run_cpcv

        cv_result = run_cpcv(recipe, data_dir=data_dir, out_dir=bundle, refresh_cache=refresh_cache)
        logger.info("cpcv-done", extra={"n_paths": cv_result.meta["n_paths"]})
```

3c. After the holdout `result = run_experiment(...)` and the `report.html` write, change the report build to pass `cv` when present. Find:

```python
    fig = build_report(result)
    write_report(fig, bundle, svg=svg)
```

and replace with:

```python
    holdout_sharpe = result.metrics.get("strategy_absolute", {}).get("information_ratio", float("nan"))
    cv_arg = None
    if cv_result is not None:
        cv_arg = {"path_sharpes": [p["sharpe"] for p in cv_result.paths], "holdout_sharpe": holdout_sharpe}
    fig = build_report(result, cv=cv_arg)
    write_report(fig, bundle, svg=svg)
```

3d. Write `cv_results.json` next to `metrics.json`. After the `metrics.json` write block, add:

```python
    if cv_result is not None:
        holdout = {
            **{m: result.metrics.get("strategy_absolute", {}).get(m, float("nan")) for m in ("annualized_return", "max_drawdown")},
            "sharpe": holdout_sharpe,
            "information_ratio": result.metrics.get("excess_return_with_cost", {}).get("information_ratio", float("nan")),
            "ending_value": result.ending_value,
        }
        (bundle / "cv_results.json").write_text(
            json.dumps(
                {"cv": cv_result.meta, "paths": cv_result.paths, "distribution": cv_result.distribution, "rank_ic": cv_result.rank_ic, "holdout": holdout},
                indent=2,
            )
        )
```

3e. Add the CV stdout line. After the existing `typer.echo(f"  trades ...")` line and before `typer.echo(f"  bundle ...")`:

```python
    if cv_result is not None:
        d = cv_result.distribution
        typer.echo(
            f"  CPCV ({cv_result.meta['n_paths']} paths, train+valid): "
            f"Sharpe {d['sharpe_mean']:.2f} ± {d['sharpe_std']:.2f} (worst {d['sharpe_worst']:.2f}) · "
            f"rank-IC {cv_result.rank_ic['mean']:.3f}"
        )
```

- [ ] **Step 4: Run, expect PASS** — `uv run pytest tests/test_experiment_command.py -v` (the e2e + the two new tests).

- [ ] **Step 5: Update `README.md` `## Usage`.** In the `zcrypto experiment` subsection: (a) add the `--quick` flag to the options list with help text "Skip CPCV; run only the single train→backtest holdout."; (b) add a sentence: "By default `experiment` runs combinatorial purged cross-validation (CPCV) over `train+valid` — writing `cv_results.json` (per-path Sharpe distribution + rank-IC) and a 4th report panel — then the single holdout backtest on `test`. `--quick` skips CPCV." Let `mdformat` regenerate the TOC on commit; do not hand-edit the `<!-- mdformat-toc -->` block.

- [ ] **Step 6: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add cli/experiment/command.py README.md tests/test_experiment_command.py
git commit -m "feat(experiment): run CPCV by default, add --quick and cv_results.json"
```

---

## Task 7: Keep the suite fast under CPCV-by-default

The existing single-run experiment tests would now trigger CPCV (minutes). Point the ones that only exercise the single run at `--quick`.

**Files:**
- Modify: `tests/test_experiment_command.py` (`test_experiment_end_to_end`)

- [ ] **Step 1: Add `--quick` to the legacy e2e invocation.** In `test_experiment_end_to_end`, add `"--quick"` to the args list (after `"--refresh-cache"`). Its assertions (bundle files, `USDT` in output, `run_meta.json`) are about the holdout, which `--quick` produces unchanged. The new `test_experiment_default_writes_cv_results` already covers the default CPCV path, so coverage is preserved.

- [ ] **Step 2: Run, expect PASS + confirm speed** — `uv run pytest tests/test_experiment_command.py -q` (the legacy e2e is now fast; the default-CPCV and run_cpcv tests carry the heavier path).

- [ ] **Step 3: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add tests/test_experiment_command.py
git commit -m "test(experiment): run the legacy single-run e2e under --quick"
```

---

## Task 8: Closeout — open-topics convention, `T0002` transition, iterations-history

Per `.claude/rules/open-topics.md` and `.claude/rules/iterations-history.md`. This task lands **after** the CPCV work above, so the `T0002` "done" statements are truthful.

**Files:**
- Modify: `.claude/rules/open-topics.md`
- Modify: `docs/open-topics/README.md`
- Modify: `docs/open-topics/T0002-validation-rigor.md`
- Modify: `docs/iterations-history.md`

- [ ] **Step 1: Enhance the open-topics rule** — add a `partial` status as a third lifecycle state:
  - In the intro paragraph, change "split into `## Open` and `## Resolved` subsections." → "split into `## Open`, `## Partially done`, and `## Resolved` subsections."
  - In *Required file shape*, annotate the front-matter as `status: open   # one of: open | partial | resolved` and add a note: a `partial` topic carries a `## Done so far` section (between `## Findings so far` and `## Suggested next steps`) recording what landed; its `## Suggested next steps` then lists only the still-open remainder.
  - Add a `## Partially completing a topic` section (before `## Closing a topic`): flip `status: open → partial` in place; insert `## Done so far` (link the commits/PRs/spec); trim `## Suggested next steps`; move the index bullet from `## Open` to the end of `## Partially done`. Note it later closes the normal way.
  - In *Closing a topic*, change the flip to `status` (`open` or `partial`) → `resolved`.
  - In *Index sync*, change "opening or closing" → "opening, partially completing, or closing", and add a **Partially completing** bullet (move from `## Open` to end of `## Partially done`, transition order) and broaden **Closing** to move from `## Open` or `## Partially done`.

- [ ] **Step 2: Add the `## Partially done` section to the index** — in `docs/open-topics/README.md`, insert a `## Partially done<a name="partially-done"></a>` section between `## Open` and `## Resolved`, move the `T0002` bullet there, and reword it:

```markdown
- [T0002 — Validation rigor (purged CV, CPCV, deflated Sharpe)](T0002-validation-rigor.md) — **[High]** purged k-fold + embargo and CPCV (per-recipe out-of-sample Sharpe distribution) landed in iter-9 (spec 00008); deflated Sharpe + PBO, the multi-recipe ranking surface they need, and MLFinLab remain deferred.
```

Remove the `T0002` bullet from `## Open`. Let `mdformat` regenerate the TOC.

- [ ] **Step 3: Transition `docs/open-topics/T0002-validation-rigor.md` to partial:**
  - Front-matter `status: open` → `status: partial`.
  - Insert a `## Done so far` section after `## Findings so far`:

```markdown
## Done so far

Landed in iter-9 (spec `docs/specs/00008-validation-rigor-cpcv-design.md`, PR <link>):

- Purged k-fold CV with an embargo sized to label-horizon + feature-lookback,
  closing the flagged train/valid/test boundary leakage (`cli/experiment/cv.py`).
- Combinatorial purged CV (CPCV) as the **default** `experiment` run: many
  purged + embargoed splits stitched into multiple backtest paths → a per-recipe
  distribution of out-of-sample Sharpe / return / max-DD (+ rank-IC), with the
  `test` window kept as an untouched final holdout (`cli/experiment/cpcv.py`,
  `cv_results.json`, the 4th report panel). `--quick` keeps the single run.
```

  - Replace `## Suggested next steps` with the deferred remainder:

```markdown
## Suggested next steps

Still open — deferred from iter-9:

- Apply the deflated Sharpe ratio (and PBO, probability of backtest overfitting)
  on top of the CPCV path distribution.
- Build the multi-recipe comparison / ranking surface deflated Sharpe needs (it
  must track the number of trials N across recipe runs) — the reason this slice
  was deferred.
- Consider Hudson & Thames MLFinLab for reference implementations.
```

  (Replace `<link>` with the actual PR URL once the PR is opened.)

- [ ] **Step 4: Append the iter-9 entry to `docs/iterations-history.md`** — a new `## <YYYY-MM-DD> — iter-9: validation rigor (CPCV)` section with bullets covering: CPCV is the default `experiment` run (purged k-fold + embargo → combinatorial paths); the new `cli/experiment/cv.py` (pure split engine) and `cli/experiment/cpcv.py` (orchestration); the 4 new `Recipe` CV fields; `--quick` for the single run; `cv_results.json` + the 4th report panel + the `CPCV (...) Sharpe ...` stdout line; the new JSONL events (`cpcv-init`, `cpcv-start`, `split-trained`, `paths-assembled`, `path-backtest`, `cv-aggregated`, `cpcv-done`); and that the open-topics convention gained a `partial` state, transitioning `T0002` to partially done. Use today's date.

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add .claude/rules/open-topics.md docs/open-topics/README.md docs/open-topics/T0002-validation-rigor.md docs/iterations-history.md
git commit -m "docs(experiment): close out iter-9 — open-topics partial state, T0002 transition, iterations-history"
```

---

## Self-review (against the spec)

- **Spec coverage:** scope cut → Task 1+4 (CV fields, deferral noted Task 8); CV output (path Sharpe dist + rank-IC, holdout) → Task 4/6; CPCV-by-default + `--quick` → Task 6; A (holdout = `run_experiment`) → Task 6 leaves it unchanged; B (N=6/k=2) → Task 1 defaults; C (purge=label_horizon, embargo=feature_lookback) → Task 2 + wired in Task 4; D (no fold early-stopping) → Task 4 `_lgb_params`; E (4th panel) → Task 5; `cv.py`/`cpcv.py` split → Task 2/4; `cv_results.json` schema → Task 6; logging events → Task 4/6; testing (pure unit, scaled integration, `--quick` parity, suite speed) → Task 2/4/6/7; closeout (open-topics rule + T0002 + README + iterations-history) → Task 6 (README) + Task 8.
- **Type consistency:** `build_cv_plan`/`assemble_paths`/`CVPlan.n_paths`/`CVSplit` used identically in Task 2 and Task 4; `CPCVResult` fields (`meta`/`paths`/`distribution`/`rank_ic`) consistent across Task 4 and Task 6; `exchange_kwargs(recipe)` defined Task 3, consumed Task 4; `build_report(result, *, stress_windows=None, cv=None)` consistent Task 5 ↔ Task 6; `cv` dict keys (`path_sharpes`, `holdout_sharpe`) match Task 5 ↔ Task 6; "sharpe" == absolute `information_ratio` consistent across Task 4/5/6.
- **No placeholders:** the only `<link>` is the not-yet-existing PR URL in a doc (Task 8), explicitly flagged to fill in at PR time.

## Iterations history

Appending the iter-9 entry to `docs/iterations-history.md` is **Task 8, Step 4** — the final task of this plan (per `.claude/rules/iterations-history.md`).
