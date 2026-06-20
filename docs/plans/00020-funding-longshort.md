# Funding-edge Monetization (market-neutral long/short) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether the iter-20 cross-sectional funding edge becomes positive absolute return once market beta is removed — via a market-neutral long/short quantile-spread evaluator computed from the existing holdout signal and reported per seed by the multi-seed holdout.

**Architecture:** qlib's executor can't short, so the L/S is a self-contained quantile-spread evaluator (the standard factor-monetization method): a pure `long_short_spread(scores, fwd_returns, *, k=5, cost_per_side)` ranks each day's instruments by predicted score, longs the top-k / shorts the bottom-k (dollar-neutral, equal-weight), and returns the daily spread net of realistic turnover costs. It is wired into the multi-seed holdout (`_light_holdout` exposes the signal; `_holdout_context` loads a 1-day-forward return panel once) so each seed reports an `ls_sharpe` + `ls_ending` alongside the existing long-only metrics.

**Tech Stack:** Python 3.12, uv, pandas, qlib (`risk_analysis` only, no init needed for the pure function), pytest, ruff.

## Global Constraints

- **The long-only holdout path stays behavior-identical** except that `_light_holdout` now returns `(report_df, signal)` instead of `report_df`, and `_holdout_metrics_for_seed` adds two keys. The existing per-seed keys (`ending_value`, `sharpe`, `psr`, `max_drawdown`) and their values are unchanged.
- **`long_short_spread` is pure** (no qlib.init / D.features / redis) — it takes the scores + forward-return Series as arguments. It may import `qlib.contrib.evaluate.risk_analysis` (a pure pandas function, no init) for the Sharpe, so `ls_sharpe` is computed by the SAME information-ratio definition as the long-only `sharpe` (comparable).
- **Construction (exact):** k=5 per leg; per date drop NaN-score/NaN-fwd rows, clamp `kk = min(k, n // 2)` (skip the date with `spread=0.0` if `kk < 1`); longs = top-`kk` by score, shorts = bottom-`kk`; `spread = mean(long fwd) − mean(short fwd)`; one-way leg turnover = `len(new_names)/kk`; `cost = cost_per_side · (turnover_long + turnover_short)`; `net = spread − cost`.
- **`cost_per_side` = the recipe's realistic per-side cost:** `FEE_PRESETS[recipe.fee_preset][0] + (0.0 if recipe.fees_only else recipe.maker_fill_haircut)` — consistent with the long-only book's cost model (iter-19).
- **`fwd_returns` convention:** `fwd_ret[t, inst] = close[t+1]/close[t] − 1` (the realized 1-day-forward return; last predict day is NaN → dropped). Leak-safe: same-day cross-section of scores + the realized next-day return only.
- `_HoldoutContext` gains an `fwd_ret` field with a **default** (`field(default=None)`) so existing constructions / the `object()` monkeypatch in `test_multiseed.py` keep working.
- ruff: line length 132, double quotes, import sorting (`select = ["I"]`). Run `uv run ruff check --fix <files>` + `uv run ruff format <files>` before each commit.
- Commit messages: `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: `long_short_spread` evaluator

**Files:**
- Create: `cli/experiment/longshort.py`
- Test: `tests/test_longshort.py`

**Interfaces:**
- Produces: `long_short_spread(scores: pd.Series, fwd_returns: pd.Series, *, k: int = 5, cost_per_side: float = 0.0) -> dict` with keys `"daily"` (pd.Series of net daily spread returns, datetime-indexed), `"sharpe"` (float, the `risk_analysis` information-ratio of the net daily series), `"ending"` (float, `∏(1+net)` growth multiple). `scores`/`fwd_returns` are `(datetime, instrument)`-MultiIndexed Series. Consumed by Task 2.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_longshort.py`:

```python
import numpy as np
import pandas as pd

from cli.experiment.longshort import long_short_spread


def _mi(date_inst_value):
    idx = pd.MultiIndex.from_tuples([(d, i) for d, i, _ in date_inst_value], names=["datetime", "instrument"])
    return pd.Series([v for *_, v in date_inst_value], index=idx)


def test_perfect_signal_positive_spread():
    # 2 dates, 6 instruments; score == next-day return → longs (top-2) beat shorts (bottom-2).
    rows_s, rows_r = [], []
    for d in pd.to_datetime(["2025-01-01", "2025-01-02"]):
        rets = {"A": 0.05, "B": 0.03, "C": 0.01, "D": -0.01, "E": -0.03, "F": -0.05}
        for inst, r in rets.items():
            rows_s.append((d, inst, r))   # score = the realized fwd return (perfect)
            rows_r.append((d, inst, r))
    out = long_short_spread(_mi(rows_s), _mi(rows_r), k=2, cost_per_side=0.0)
    # top-2 (A,B) mean 0.04 minus bottom-2 (E,F) mean -0.04 = +0.08 each day.
    assert out["daily"].round(6).tolist() == [0.08, 0.08]
    assert out["ending"] > 1.0
    assert out["sharpe"] > 0.0


def test_inverted_signal_negative_spread():
    rets = {"A": 0.05, "B": -0.05}
    d = pd.Timestamp("2025-01-01")
    scores = _mi([(d, "A", -1.0), (d, "B", 1.0)])  # score inverted vs return
    fwd = _mi([(d, "A", 0.05), (d, "B", -0.05)])
    out = long_short_spread(scores, fwd, k=1, cost_per_side=0.0)
    # long B (score 1.0, ret -0.05), short A (ret 0.05) → -0.05 - 0.05 = -0.10
    assert out["daily"].round(6).tolist() == [-0.10]


def test_turnover_cost_subtracted():
    # day1 longs={A}, shorts={C}; day2 the book flips entirely → full turnover both legs.
    d1, d2 = pd.to_datetime(["2025-01-01", "2025-01-02"])
    scores = _mi([(d1, "A", 1.0), (d1, "B", 0.0), (d1, "C", -1.0),
                  (d2, "A", -1.0), (d2, "B", 0.0), (d2, "C", 1.0)])
    fwd = _mi([(d1, "A", 0.0), (d1, "B", 0.0), (d1, "C", 0.0),
               (d2, "A", 0.0), (d2, "B", 0.0), (d2, "C", 0.0)])  # zero returns → isolate cost
    out = long_short_spread(scores, fwd, k=1, cost_per_side=0.001)
    # day1: longs={A} (new), shorts={C} (new) → turnover 1+1 → cost 0.002; spread 0 → net -0.002
    # day2: longs={C} (new vs {A}), shorts={A} (new vs {C}) → turnover 1+1 → cost 0.002 → net -0.002
    assert out["daily"].round(6).tolist() == [-0.002, -0.002]


def test_clamps_k_when_universe_small():
    d = pd.Timestamp("2025-01-01")
    scores = _mi([(d, "A", 1.0), (d, "B", -1.0)])  # n=2, k=5 → kk=min(5, 1)=1
    fwd = _mi([(d, "A", 0.02), (d, "B", -0.02)])
    out = long_short_spread(scores, fwd, k=5, cost_per_side=0.0)
    assert out["daily"].round(6).tolist() == [0.04]  # long A 0.02 - short B -0.02


def test_nan_rows_dropped_and_empty_date_is_zero():
    d1, d2 = pd.to_datetime(["2025-01-01", "2025-01-02"])
    # d2 has only 1 non-NaN instrument → kk=0 → spread 0.0
    scores = _mi([(d1, "A", 1.0), (d1, "B", -1.0), (d2, "A", 1.0), (d2, "B", np.nan)])
    fwd = _mi([(d1, "A", 0.02), (d1, "B", -0.02), (d2, "A", 0.02), (d2, "B", 0.02)])
    out = long_short_spread(scores, fwd, k=1, cost_per_side=0.0)
    assert out["daily"].round(6).tolist() == [0.04, 0.0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_longshort.py -v`
Expected: FAIL — `ModuleNotFoundError: cli.experiment.longshort`.

- [ ] **Step 3: Implement `longshort.py`**

```python
"""Market-neutral long/short quantile-spread evaluator (see docs/specs/00020).

qlib's SimulatorExecutor cannot short, so a cross-sectional signal's monetizable form — the
long-short quantile spread — is computed directly from the model's prediction scores + the
realized forward returns. Per date: long the top-k by score, short the bottom-k (equal weight,
dollar-neutral); the daily spread is `mean(long fwd) - mean(short fwd)`, net of realistic
per-side turnover costs. Pure (no qlib.init / D.features) so it is unit-testable in isolation.
"""

from __future__ import annotations

import pandas as pd


def long_short_spread(
    scores: pd.Series,
    fwd_returns: pd.Series,
    *,
    k: int = 5,
    cost_per_side: float = 0.0,
) -> dict:
    """Daily dollar-neutral long-top-k / short-bottom-k spread, net of turnover cost.

    `scores` / `fwd_returns` are (datetime, instrument)-indexed Series. Returns
    {"daily": Series, "sharpe": float, "ending": float}.
    """
    df = pd.DataFrame({"score": scores, "fwd": fwd_returns}).dropna()
    daily: dict = {}
    prev_long: set = set()
    prev_short: set = set()
    for dt, g in df.groupby(level="datetime"):
        n = len(g)
        kk = min(k, n // 2)
        if kk < 1:
            daily[dt] = 0.0
            prev_long, prev_short = set(), set()
            continue
        g = g.sort_values("score")
        shorts = g.head(kk)
        longs = g.tail(kk)
        spread = float(longs["fwd"].mean() - shorts["fwd"].mean())
        long_set = set(longs.index.get_level_values("instrument"))
        short_set = set(shorts.index.get_level_values("instrument"))
        turnover = len(long_set - prev_long) / kk + len(short_set - prev_short) / kk
        daily[dt] = spread - cost_per_side * turnover
        prev_long, prev_short = long_set, short_set

    s = pd.Series(daily).sort_index()
    sharpe = _sharpe(s)
    ending = float((1.0 + s).prod())
    return {"daily": s, "sharpe": sharpe, "ending": ending}


def _sharpe(net: pd.Series) -> float:
    """Annualized information ratio of the daily net series (qlib's risk_analysis definition).

    Matches the long-only holdout `sharpe` so the two are directly comparable.
    """
    if len(net) < 2 or net.std() == 0:
        return 0.0
    from qlib.contrib.evaluate import risk_analysis

    return float(risk_analysis(net, freq="day").loc["information_ratio"].iloc[0])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_longshort.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix cli/experiment/longshort.py tests/test_longshort.py
uv run ruff format cli/experiment/longshort.py tests/test_longshort.py
git add cli/experiment/longshort.py tests/test_longshort.py
git commit -m "feat(experiment): add long_short_spread market-neutral evaluator"
```

---

### Task 2: wire the L/S spread into the multi-seed holdout

**Files:**
- Modify: `cli/experiment/multiseed.py` (`_HoldoutContext` field; `_holdout_context` loads `fwd_ret`; `_light_holdout` returns `(report_df, signal)`; `_holdout_metrics_for_seed` adds `ls_sharpe`/`ls_ending`)
- Test: `tests/test_multiseed.py` (extend)

**Interfaces:**
- Consumes: `long_short_spread` (Task 1); the existing `_HoldoutContext`, `_light_holdout`, `_holdout_metrics_for_seed`.
- Produces: per-seed dict now also carries `ls_sharpe: float`, `ls_ending: float` (auto-aggregated by `summarize_seed_metrics`, which is generic over keys).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_multiseed.py` (tests the metric assembly with the heavy seam monkeypatched — no qlib/redis):

```python
def test_holdout_metrics_includes_long_short(monkeypatch):
    import pandas as pd

    import cli.experiment.multiseed as ms

    # Synthetic holdout: 2 dates × 4 instruments; report_df is the long-only daily report.
    dates = pd.to_datetime(["2025-01-01", "2025-01-02"])
    insts = ["A", "B", "C", "D"]
    idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
    signal = pd.Series([4, 3, 2, 1, 4, 3, 2, 1], index=idx, dtype=float)  # A>B>C>D each day
    fwd = pd.Series([0.05, 0.0, 0.0, -0.05] * 2, index=idx, dtype=float)  # A up, D down
    report_df = pd.DataFrame(
        {"return": [0.01, 0.01], "cost": [0.0, 0.0]}, index=dates
    )

    monkeypatch.setattr(ms, "_light_holdout", lambda recipe, *, seed, deterministic, ctx: (report_df, signal))

    class _Recipe:
        account = 10_000.0
        fee_preset = "vip2_bnb"
        fees_only = False
        maker_fill_haircut = 0.0

    class _Ctx:
        fwd_ret = fwd

    out = ms._holdout_metrics_for_seed(_Recipe(), 1, False, _Ctx())
    # long-only keys still present
    assert {"ending_value", "sharpe", "psr", "max_drawdown"} <= set(out)
    # new L/S keys present; k=1 leg → long A (0.05), short D (-0.05) → +0.10/day, positive
    assert "ls_sharpe" in out and "ls_ending" in out
    assert out["ls_ending"] > 1.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_multiseed.py::test_holdout_metrics_includes_long_short -v`
Expected: FAIL — `_light_holdout` returns a tuple the current `_holdout_metrics_for_seed` doesn't unpack / no `ls_*` keys.

- [ ] **Step 3: Add the `fwd_ret` field to `_HoldoutContext`**

In `cli/experiment/multiseed.py`, in the `@dataclass class _HoldoutContext`, add a field (after `predict_dates`, before `_cm`):

```python
    fwd_ret: object = field(default=None)  # 1-day-forward $close-return Series (datetime, instrument); for the L/S spread
```

(Ensure `from dataclasses import dataclass, field` — add `field` to the existing import if absent.)

- [ ] **Step 4: Load `fwd_ret` in `_holdout_context`**

In `_holdout_context`, after the `predict_dates = {...}` line and before the `except BaseException:`/`return`, build the forward-return panel over the holdout window and pass it to the constructor. Add:

```python
        from qlib.data import D

        predict_close = D.features(
            list(recipe.universe), ["$close"], start_time=predict_start, end_time=predict_end, freq="day"
        )["$close"]
        wide_close = predict_close.unstack(level="instrument")
        fwd_ret = (wide_close.shift(-1) / wide_close - 1.0).stack(future_stack=True)
        fwd_ret.index.names = ["datetime", "instrument"]
```

and add `fwd_ret=fwd_ret,` to the `_HoldoutContext(...)` constructor call.

- [ ] **Step 5: `_light_holdout` returns `(report_df, signal)`**

In `_light_holdout`, change the final `return pmd[pmd_key][0]` to:

```python
    return pmd[pmd_key][0], signal
```

(`signal` is already a local variable — the LightGBM predictions Series built earlier in the function.) Update the docstring's "return the daily `report_df`" to "return the daily `report_df` and the prediction `signal`".

- [ ] **Step 6: `_holdout_metrics_for_seed` computes the L/S metrics**

In `_holdout_metrics_for_seed`, change the `report_df = _light_holdout(...)` line and the return dict:

```python
    from cli.experiment.longshort import long_short_spread
    from cli.experiment.recipes.base import FEE_PRESETS

    report_df, signal = _light_holdout(recipe, seed=seed, deterministic=deterministic, ctx=ctx)

    cost_adj = report_df["return"] - report_df["cost"]
    abs_df = risk_analysis(cost_adj, freq="day")
    account_curve = recipe.account * (1 + report_df["return"]).cumprod()

    cost_per_side = FEE_PRESETS[recipe.fee_preset][0] + (0.0 if recipe.fees_only else recipe.maker_fill_haircut)
    ls = long_short_spread(signal, ctx.fwd_ret, k=5, cost_per_side=cost_per_side)

    return {
        "ending_value": float(account_curve.iloc[-1]),
        "sharpe": float(abs_df.loc["information_ratio"].iloc[0]),
        "psr": _psr(cost_adj.to_numpy()),
        "max_drawdown": float(abs_df.loc["max_drawdown"].iloc[0]),
        "ls_sharpe": ls["sharpe"],
        "ls_ending": ls["ending"],
    }
```

(The `risk_analysis` and `_psr` imports already exist at the top of the function — keep them.)

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_multiseed.py -v`
Expected: PASS (the new test + all existing multiseed tests — `summarize_seed_metrics` aggregates `ls_sharpe`/`ls_ending` automatically; `run_holdout_seeds`'s monkeypatched test still passes since it stubs `_holdout_metrics_for_seed`).

- [ ] **Step 8: Lint + targeted suite + commit**

```bash
uv run ruff check --fix cli/experiment/multiseed.py tests/test_multiseed.py
uv run ruff format cli/experiment/multiseed.py tests/test_multiseed.py
uv run pytest tests/test_multiseed.py tests/test_longshort.py -q
git add cli/experiment/multiseed.py tests/test_multiseed.py
git commit -m "feat(experiment): report long/short spread metrics in the multi-seed holdout"
```

Expected: the targeted suite passes.

---

## Closeout (operational — run by the orchestrator after Tasks 1-2 land, NOT a subagent task)

1. **Run the A/B** (redis up via `scripts/redis.sh start`), `--seeds 16 --deterministic --quick`, realistic-cost default: `funding_steady` and `steady`. Each `holdout_seeds.json` now carries per-seed `ls_sharpe` + `ls_ending` (and the summary aggregates them).
2. **Compute the verdict:**
   - **Paired per-seed `ls_sharpe`** `funding_steady − steady` (funding's market-neutral contribution) vs the seed-noise band.
   - **`ls_sharpe` distribution vs the long-only `sharpe` distribution** for each recipe (does neutralizing the −32%→−65% beta turn the edge positive / materially better?).
   - Note the **turnover-cost reality** (the daily L/S can be high-turnover; report `ls_ending` net of the realistic cost).
3. **iter-21 iterations-history entry:** the `long_short_spread` evaluator (+ the qlib-can't-short rationale) and the monetization verdict — is the funding edge monetizable market-neutral, net of costs?

---

## Self-Review

**Spec coverage:** Decision 1 (spread evaluator, not a qlib strategy) → Task 1; Decision 2 (k=5/daily/1d-fwd/dollar-neutral/eq-wt) → Task 1 (`long_short_spread` + the construction tests); Decision 3 (realistic per-side cost on turnover) → Task 1 (cost in the function) + Task 2 (`cost_per_side` from the recipe); Decision 4 (multi-seed integration: signal exposure, `ctx.fwd_ret`, `ls_sharpe`/`ls_ending`) → Task 2; Decision 5 (A/B on paired `ls_sharpe`) → Closeout 1-2. Verdict + iter-21 history → Closeout 3.

**Placeholder scan:** No TBD/TODO. All code steps carry full code; the construction formula + the fwd-return convention are concrete. The verdict values are correctly closeout (the A/B runs).

**Type consistency:** `long_short_spread(scores, fwd_returns, *, k=5, cost_per_side=0.0) -> {"daily","sharpe","ending"}` identical across Task 1 code, Task 1 tests, and Task 2's call. `_HoldoutContext.fwd_ret` added with a default (compat with `test_multiseed.py`'s `object()` stub — note: the existing `run_holdout_seeds` monkeypatch test stubs `_holdout_metrics_for_seed` and `_holdout_context`, so it never touches `fwd_ret`). `_light_holdout` now returns `(report_df, signal)` — its only caller `_holdout_metrics_for_seed` is updated to unpack it. `cost_per_side` formula matches the spec (`FEE_PRESETS[fee_preset][0] + maker_fill_haircut` unless `fees_only`).
