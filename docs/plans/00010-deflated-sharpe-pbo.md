# Deflated Sharpe, PBO, and the `rank` command — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve open-topic `T0002` — add per-recipe PSR (probabilistic Sharpe) to every experiment run and a new `zcrypto rank` command that applies the deflated Sharpe ratio + PBO across persisted runs (trials). All from existing daily-kline backtest outputs; no new data.

**Architecture:** A pure stats module (`cli/experiment/stats.py`: `sharpe`, `psr`, `expected_max_sharpe`, `deflated_sharpe`, `pbo_cscv`) with no qlib. `command.py` computes PSR on the holdout returns, persists a per-run `returns.csv`, and surfaces PSR in `cv_results.json`/report/stdout. A new top-level `rank` command scans `runs/`, treats each bundle as a trial, and reports DSR + PBO + a ranked table.

**Tech Stack:** Python 3.12, uv, numpy, scipy (already available via pyqlib), pandas, Typer, plotly; pytest + Typer `CliRunner`.

**Spec:** `docs/specs/00010-deflated-sharpe-pbo-design.md`. **Branch:** `feat/deflated-sharpe-pbo`.

Gate after each task: `uv run ruff check && uv run ruff format --check && uv run pytest -q` (redis-gated tests skip without redis; `scripts/redis.sh start`). Commit only on green. **Deferred-import discipline:** keep `zcrypto --help` fast — `stats`/`numpy`/`pandas` must NOT be imported at the module top of `command.py` or `rank.py`; defer them into function bodies (matches the existing pattern in `command.py`).

---

## File structure

| File | Responsibility | Task |
| --- | --- | --- |
| `cli/experiment/stats.py` (new) | Pure PSR / DSR / PBO, no qlib | 1 |
| `cli/experiment/command.py` | Holdout PSR; persist `returns.csv`; `cv_results.json` `psr`; stdout; `cv_arg["holdout_psr"]` | 2 |
| `cli/experiment/report.py` | Relabel the path band "(descriptive)"; holdout marker → different-period + PSR | 3 |
| `cli/experiment/rank.py` (new) + `cli/__main__.py` | `zcrypto rank`: scan `runs/` → DSR + PBO → ranked table + `runs/rank.json` | 4 |
| README, `docs/open-topics/T0002` + index, `docs/iterations-history.md` | Closeout (`T0002` → resolved) | 5 |

---

## Task 1: Stats module (`stats.py`)

**Files:** Create `cli/experiment/stats.py`; Test `tests/test_experiment_stats.py` (new).

- [ ] **Step 1: Write the failing tests** — create `tests/test_experiment_stats.py`:

```python
import math

import numpy as np
import pytest

from cli.experiment.stats import deflated_sharpe, expected_max_sharpe, pbo_cscv, psr, sharpe


def test_sharpe_basic_and_degenerate():
    assert sharpe([1.0, 1.0, 1.0]) == 0.0  # zero variance
    assert sharpe([0.01]) == 0.0  # too short
    r = np.array([0.01, -0.005, 0.02, 0.0, 0.015])
    assert abs(sharpe(r) - r.mean() / r.std(ddof=1)) < 1e-12


def test_psr_zero_mean_is_about_half():
    r = np.random.default_rng(0).normal(0.0, 0.01, 5000)
    assert abs(psr(r) - 0.5) < 0.06  # SR ~ 0 → PSR ~ 0.5


def test_psr_grows_with_sample_length():
    short = np.random.default_rng(1).normal(0.001, 0.01, 200)
    long = np.random.default_rng(1).normal(0.001, 0.01, 6000)
    assert 0.5 < psr(short) <= 1.0
    assert psr(long) > psr(short)  # more data, same edge → higher confidence


def test_psr_degenerate():
    assert math.isnan(psr([0.01]))  # n < 2
    assert math.isnan(psr([0.01, 0.01]))  # zero variance


def test_expected_max_sharpe_grows_with_trials():
    small = expected_max_sharpe([0.0, 0.1, -0.1, 0.05])
    big = expected_max_sharpe([0.0, 0.1, -0.1, 0.05] * 25)  # more trials, same spread
    assert big > small > 0
    assert math.isnan(expected_max_sharpe([0.1]))  # n < 2


def test_deflated_sharpe_decreases_with_more_trials():
    rng = np.random.default_rng(2)
    best = rng.normal(0.001, 0.01, 1000)
    sr_best = sharpe(best)
    few = deflated_sharpe(best, [sr_best, 0.0, -0.02, 0.02])
    many = deflated_sharpe(best, [sr_best, *list(rng.normal(0, 0.05, 200))])
    assert few > many  # more trials → harder to beat the max-null → lower DSR
    assert math.isnan(deflated_sharpe(best, [sr_best]))  # n < 2 → NaN


def test_pbo_low_for_dominant_strategy():
    rng = np.random.default_rng(3)
    M = np.hstack([rng.normal(0.003, 0.01, (320, 1)), rng.normal(0.0, 0.01, (320, 4))])
    res = pbo_cscv(M, n_splits=16)
    assert res["n_combinations"] == math.comb(16, 8)
    assert res["pbo"] < 0.3  # a real edge generalizes out-of-sample


def test_pbo_high_for_pure_noise():
    M = np.random.default_rng(4).normal(0, 0.01, (320, 8))  # no real edge
    assert 0.3 < pbo_cscv(M, n_splits=16)["pbo"] <= 1.0


def test_pbo_edge_cases():
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((100, 3)), n_splits=15)  # odd
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((10, 3)), n_splits=16)  # n_splits > t
    assert math.isnan(pbo_cscv(np.zeros((100, 1)))["pbo"])  # < 2 trials
```

- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/test_experiment_stats.py -v` → `ModuleNotFoundError`.

- [ ] **Step 3: Create `cli/experiment/stats.py`**:

```python
"""Backtest-validation statistics: probabilistic / deflated Sharpe and PBO.

Pure functions on plain sequences — no qlib. All Sharpe inputs are per-period
(non-annualized). References: Bailey & López de Prado (2012, PSR; 2014, DSR);
Bailey, Borwein, López de Prado, Zhu (2015, PBO / CSCV).
"""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np
from scipy.stats import norm

_EULER_GAMMA = 0.5772156649015329


def sharpe(returns) -> float:
    """Per-period (non-annualized) Sharpe of a return series; 0.0 if degenerate."""
    r = np.asarray(returns, dtype="float64")
    if r.size < 2:
        return 0.0
    sd = r.std(ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return 0.0
    return float(r.mean() / sd)


def psr(returns, sr_benchmark: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio: P(true per-period SR > sr_benchmark).

    Corrects the observed Sharpe for sample length and the return distribution's
    skewness and (non-excess) kurtosis. Returns a probability in [0, 1], or NaN
    for a degenerate series.
    """
    r = np.asarray(returns, dtype="float64")
    n = r.size
    if n < 2:
        return float("nan")
    sd = r.std(ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return float("nan")
    sr = float(r.mean() / sd)
    m = r - r.mean()
    s2 = float((m**2).mean())
    if s2 <= 0:
        return float("nan")
    g3 = float((m**3).mean() / s2**1.5)  # skewness
    g4 = float((m**4).mean() / s2**2)  # non-excess kurtosis (normal == 3)
    denom = math.sqrt(max(1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr**2, 1e-12))
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / denom
    return float(norm.cdf(z))


def expected_max_sharpe(sr_trials) -> float:
    """Expected maximum per-period Sharpe under the null across N >= 2 trials."""
    s = np.asarray(sr_trials, dtype="float64")
    n = s.size
    if n < 2:
        return float("nan")
    var = float(s.var(ddof=1))
    if not np.isfinite(var) or var <= 0:
        return 0.0
    sigma = math.sqrt(var)
    z1 = float(norm.ppf(1.0 - 1.0 / n))
    z2 = float(norm.ppf(1.0 - 1.0 / (n * math.e)))
    return float(sigma * ((1.0 - _EULER_GAMMA) * z1 + _EULER_GAMMA * z2))


def deflated_sharpe(returns_best, sr_trials) -> float:
    """Deflated Sharpe Ratio: PSR of the best trial against the expected-max-Sharpe null.

    `sr_trials`: per-period Sharpe of every trial (including the best). Returns
    P(the best trial's true SR exceeds what N random trials would yield by luck),
    or NaN for fewer than 2 trials.
    """
    s = np.asarray(sr_trials, dtype="float64")
    if s.size < 2:
        return float("nan")
    return psr(returns_best, sr_benchmark=expected_max_sharpe(s))


def pbo_cscv(returns_matrix, n_splits: int = 16) -> dict:
    """Probability of Backtest Overfitting via Combinatorially-Symmetric CV.

    `returns_matrix`: 2-D (rows = aligned time observations, cols = trials).
    Returns ``{"pbo": float, "logits": list[float], "n_combinations": int}``.
    PBO is the fraction of in-sample/out-of-sample splits where the IS-best trial
    lands OOS below the median. NaN / empty for fewer than 2 trials.
    """
    matrix = np.asarray(returns_matrix, dtype="float64")
    if matrix.ndim != 2:
        raise ValueError("returns_matrix must be 2-D (time x trials)")
    t, n = matrix.shape
    if n < 2:
        return {"pbo": float("nan"), "logits": [], "n_combinations": 0}
    if n_splits % 2 != 0:
        raise ValueError(f"n_splits must be even, got {n_splits}")
    if n_splits > t:
        raise ValueError(f"n_splits={n_splits} exceeds the number of observations t={t}")
    groups = [g for g in np.array_split(np.arange(t), n_splits) if g.size]
    s = len(groups)
    logits: list[float] = []
    for is_combo in combinations(range(s), s // 2):
        is_set = set(is_combo)
        is_rows = np.concatenate([groups[i] for i in is_combo])
        oos_rows = np.concatenate([groups[i] for i in range(s) if i not in is_set])
        is_sr = np.array([sharpe(matrix[is_rows, j]) for j in range(n)])
        oos_sr = np.array([sharpe(matrix[oos_rows, j]) for j in range(n)])
        best = int(np.argmax(is_sr))
        rank = int((oos_sr <= oos_sr[best]).sum())  # 1..n  (n == OOS-best)
        omega = min(max(rank / (n + 1), 1e-6), 1 - 1e-6)
        logits.append(math.log(omega / (1.0 - omega)))
    pbo = float(np.mean([1.0 if x <= 0 else 0.0 for x in logits])) if logits else float("nan")
    return {"pbo": pbo, "logits": logits, "n_combinations": len(logits)}
```

- [ ] **Step 4: Run, expect PASS** — `uv run pytest tests/test_experiment_stats.py -v`. (The PBO/DSR statistical thresholds use fixed RNG seeds, so they're deterministic; if a threshold is marginally off for a seed, nudge the seed — do NOT loosen a threshold so far it stops discriminating overfit from real.)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add cli/experiment/stats.py tests/test_experiment_stats.py
git commit -m "feat(experiment): add PSR / deflated-Sharpe / PBO statistics module"
```

---

## Task 2: Per-recipe PSR + `returns.csv` (`command.py`)

**Files:** Modify `cli/experiment/command.py`; Test `tests/test_experiment_command.py` (extend).

- [ ] **Step 1: Write the tests** — append to `tests/test_experiment_command.py` (helpers `_redis_up`, `runner`, imports already present):

```python
@pytest.mark.skipif(not _redis_up(), reason="needs redis (scripts/redis.sh start)")
def test_experiment_writes_returns_and_psr(tmp_path, monkeypatch):
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
    assert (bundle / "returns.csv").exists()  # persisted in both modes
    assert "PSR" in result.output  # stdout PSR line
```

Also add one assertion to the existing `test_experiment_default_writes_cv_results` (after `cv = json.loads(...)`): `assert "psr" in cv["holdout"]`.

- [ ] **Step 2: Run, expect FAIL** — `scripts/redis.sh start` then `uv run pytest tests/test_experiment_command.py::test_experiment_writes_returns_and_psr -v` → no `returns.csv` / no PSR in output.

- [ ] **Step 3: Edit `cli/experiment/command.py`.**

3a. In the deferred-import block inside `experiment()` (next to `from cli.experiment.report import build_report, write_report`), add:

```python
    from cli.experiment.stats import psr
```

3b. Immediately after `result = run_experiment(...)` and its `logger.info("run-done", ...)` line, compute the holdout returns + PSR:

```python
    holdout_returns = result.report_df["return"] - result.report_df["cost"]
    holdout_psr = psr(holdout_returns.to_numpy())
```

3c. Add `holdout_psr` to the `cv_arg` dict (currently builds `{"path_sharpes": ..., "holdout_sharpe": holdout_sharpe}`):

```python
        cv_arg = {"path_sharpes": [p["sharpe"] for p in cv_result.paths], "holdout_sharpe": holdout_sharpe, "holdout_psr": holdout_psr}
```

3d. Persist `returns.csv` (unconditional — both modes). Add right after the `metrics.json` write block:

```python
    # --- returns.csv (holdout cost-adjusted daily returns; consumed by `zcrypto rank`) ---
    _ret = holdout_returns.rename("ret")
    _ret.index.name = "date"
    _ret.to_csv(bundle / "returns.csv")
```

3e. Add `"psr"` to the `holdout` dict written into `cv_results.json` (the dict currently has `sharpe`, `annualized_return`, `max_drawdown`, `information_ratio`, `ending_value`):

```python
            "psr": holdout_psr,  # P(true holdout Sharpe > 0), corrected for length + non-normality
```

3f. Add a stdout PSR line, immediately after the `information_ratio` echo line:

```python
    typer.echo(f"  holdout PSR       : {holdout_psr:+.3f}")
```

- [ ] **Step 4: Run, expect PASS** — `uv run pytest tests/test_experiment_command.py::test_experiment_writes_returns_and_psr -v`.

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add cli/experiment/command.py tests/test_experiment_command.py
git commit -m "feat(experiment): compute holdout PSR, persist returns.csv, surface PSR"
```

---

## Task 3: Report — relabel band + holdout marker, show PSR (`report.py`)

**Files:** Modify `cli/experiment/report.py`; Test `tests/test_experiment_report.py` (append).

- [ ] **Step 1: Write the failing test** — append to `tests/test_experiment_report.py`:

```python
def test_build_report_psr_and_holdout_relabel():
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
    cv = {"path_sharpes": [0.2, 0.5, 0.8], "holdout_sharpe": 0.6, "holdout_psr": 0.73}
    fig = build_report(result, cv=cv)
    texts = " || ".join(a.text for a in fig.layout.annotations if a.text)
    assert "descriptive" in texts  # path band relabelled, not a CI
    assert "test period" in texts  # holdout marker relabelled (different period)
    assert "PSR" in texts  # PSR surfaced
```

- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/test_experiment_report.py::test_build_report_psr_and_holdout_relabel -v`.

- [ ] **Step 3: Edit `cli/experiment/report.py`.**

3a. Relabel the 4th-panel title — change:

```python
        titles.append("CPCV out-of-sample Sharpe distribution")
```

to:

```python
        titles.append("CPCV OOS Sharpe distribution (descriptive)")
```

3b. Relabel the holdout marker + add PSR — change the `add_vline(...)` argument:

```python
            annotation_text="holdout",
```

to:

```python
            annotation_text=f"holdout (test period) · PSR {cv.get('holdout_psr', float('nan')):.2f}",
```

- [ ] **Step 4: Run, expect PASS** — `uv run pytest tests/test_experiment_report.py -v`.

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add cli/experiment/report.py tests/test_experiment_report.py
git commit -m "feat(experiment): relabel CPCV band as descriptive, show holdout PSR + period"
```

---

## Task 4: `rank` command (`rank.py` + `__main__.py`)

**Files:** Create `cli/experiment/rank.py`; Modify `cli/__main__.py`; Test `tests/test_experiment_rank.py` (new).

- [ ] **Step 1: Write the failing tests** — create `tests/test_experiment_rank.py`:

```python
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
from typer.testing import CliRunner

from cli.__main__ import app

runner = CliRunner()


def _bundle(out, recipe, run, dates, rets):
    d = out / recipe / run
    d.mkdir(parents=True)
    pd.DataFrame({"date": dates, "ret": rets}).to_csv(d / "returns.csv", index=False)


def test_rank_two_trials(tmp_path):
    dates = pd.date_range("2025-01-01", periods=320, freq="D")
    rng = np.random.default_rng(0)
    _bundle(tmp_path, "skeleton", "20250101T000000Z", dates, rng.normal(0.002, 0.01, 320))
    _bundle(tmp_path, "variantb", "20250102T000000Z", dates, rng.normal(0.0, 0.01, 320))
    res = runner.invoke(app, ["rank", "--out", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert "2 trials" in res.output
    rj = json.loads((tmp_path / "rank.json").read_text())
    assert rj["n_trials"] == 2
    assert {"dsr_best", "pbo", "trials", "window"} <= set(rj)
    assert len(rj["trials"]) == 2
    assert all({"recipe", "run", "sharpe", "psr"} <= set(t) for t in rj["trials"])


def test_rank_no_trials_errors(tmp_path):
    res = runner.invoke(app, ["rank", "--out", str(tmp_path)])
    assert res.exit_code != 0
    assert "no trials" in res.output.lower()


def test_rank_single_trial_na(tmp_path):
    dates = pd.date_range("2025-01-01", periods=300, freq="D")
    _bundle(tmp_path, "only", "r1", dates, np.random.default_rng(1).normal(0.001, 0.01, 300))
    res = runner.invoke(app, ["rank", "--out", str(tmp_path)])
    assert res.exit_code == 0, res.output
    rj = json.loads((tmp_path / "rank.json").read_text())
    assert rj["n_trials"] == 1
    assert math.isnan(rj["dsr_best"]) and math.isnan(rj["pbo"])  # need >= 2 trials
```

- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/test_experiment_rank.py -v` → no `rank` command.

- [ ] **Step 3: Create `cli/experiment/rank.py`** (light module-level imports; `numpy`/`pandas`/`stats` deferred so `zcrypto --help` stays fast):

```python
"""`zcrypto rank` — rank persisted experiment runs as trials; report DSR + PBO."""

from __future__ import annotations

import json
from pathlib import Path

import typer


def _load_trials(out_dir: Path) -> list[dict]:
    """Return [{recipe, run, returns}] for every bundle under out_dir with a returns.csv."""
    import pandas as pd

    trials: list[dict] = []
    if not out_dir.is_dir():
        return trials
    for recipe_dir in sorted(p for p in out_dir.iterdir() if p.is_dir() and p.name != "mlruns"):
        for run_dir in sorted(p for p in recipe_dir.iterdir() if p.is_dir()):
            rcsv = run_dir / "returns.csv"
            if not rcsv.exists():
                continue
            series = pd.read_csv(rcsv, parse_dates=["date"]).set_index("date")["ret"]
            trials.append({"recipe": recipe_dir.name, "run": run_dir.name, "returns": series})
    return trials


def rank(
    out: Path = typer.Option(Path("runs"), "--out", help="Run-bundle root to scan for trials.", file_okay=False),
    n_splits: int = typer.Option(16, "--n-splits", help="CSCV splits for PBO (must be even)."),
) -> None:
    """Rank all persisted runs as trials; report the deflated Sharpe ratio + PBO."""
    import numpy as np

    from cli.experiment.stats import deflated_sharpe, pbo_cscv, psr, sharpe
    from cli.logging import get_logger

    logger = get_logger("experiment.rank")
    out = Path(out)
    trials = _load_trials(out)
    logger.info("rank-scan", extra={"n_trials": len(trials), "out": str(out)})
    if not trials:
        typer.echo(f"ERROR: no trials with returns.csv under {out}", err=True)
        raise typer.Exit(code=1)

    common = trials[0]["returns"].index
    for tr in trials[1:]:
        common = common.intersection(tr["returns"].index)
    if len(common) == 0:
        typer.echo("ERROR: trials share no common dates; cannot rank.", err=True)
        raise typer.Exit(code=1)
    common = common.sort_values()
    logger.info("rank-aligned", extra={"t": len(common), "from": str(common.min().date()), "to": str(common.max().date())})

    matrix = np.column_stack([tr["returns"].reindex(common).to_numpy() for tr in trials])
    per_trial = [
        {"recipe": tr["recipe"], "run": tr["run"], "sharpe": sharpe(matrix[:, j]), "psr": psr(matrix[:, j])}
        for j, tr in enumerate(trials)
    ]
    n = len(trials)
    best = max(range(n), key=lambda j: per_trial[j]["sharpe"])
    sr_trials = [pt["sharpe"] for pt in per_trial]
    dsr = deflated_sharpe(matrix[:, best], sr_trials) if n >= 2 else float("nan")
    pbo = pbo_cscv(matrix, n_splits)["pbo"] if n >= 2 else float("nan")
    logger.info("rank-done", extra={"dsr": dsr, "pbo": pbo})

    typer.echo(f"{n} trials over {common.min().date()}..{common.max().date()} ({len(common)} days)")
    if n >= 2:
        typer.echo(f"  DSR(best) = {dsr:.4f}   PBO = {pbo:.4f}")
    else:
        typer.echo("  DSR / PBO: N/A (need >= 2 trials)")
    typer.echo(f"  {'rank':<5}{'recipe':<16}{'run':<22}{'sharpe':>9}{'PSR':>8}")
    for rank_i, j in enumerate(sorted(range(n), key=lambda j: per_trial[j]["sharpe"], reverse=True), 1):
        pt = per_trial[j]
        mark = " *" if j == best else ""
        typer.echo(f"  {rank_i:<5}{pt['recipe']:<16}{pt['run']:<22}{pt['sharpe']:>9.4f}{pt['psr']:>8.3f}{mark}")

    (out / "rank.json").write_text(
        json.dumps(
            {
                "n_trials": n,
                "window": [str(common.min().date()), str(common.max().date()), len(common)],
                "n_splits": n_splits,
                "trials": per_trial,
                "dsr_best": dsr,
                "pbo": pbo,
            },
            indent=2,
        )
    )
    typer.echo(f"  wrote {out / 'rank.json'}")
```

- [ ] **Step 4: Register the command** — in `cli/__main__.py`, alongside the existing `app.command("experiment")(experiment)` registration, add the import (with the other command imports) and registration:

```python
from cli.experiment.rank import rank
...
app.command("rank")(rank)
```

(Match the file's existing import/registration style; `rank.py`'s module-level imports are light, so this does not slow `zcrypto --help`.)

- [ ] **Step 5: Run, expect PASS** — `uv run pytest tests/test_experiment_rank.py -v`; sanity-check `uv run zcrypto rank --help` and `uv run zcrypto --help` (still fast).

- [ ] **Step 6: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add cli/experiment/rank.py cli/__main__.py tests/test_experiment_rank.py
git commit -m "feat(experiment): add zcrypto rank (deflated Sharpe + PBO across run trials)"
```

---

## Task 5: Closeout — README, `T0002` resolved, iterations-history

**Files:** Modify `README.md`, `docs/open-topics/T0002-validation-rigor.md`, `docs/open-topics/README.md`, `docs/iterations-history.md`.

- [ ] **Step 1: README `## Usage`.** Document the new top-level `zcrypto rank` command (`--out`, `--n-splits`; scans run bundles, reports the deflated Sharpe ratio of the best trial + PBO + a ranked table, writes `runs/rank.json`) and note that each `experiment` run now reports a **holdout PSR** and persists `returns.csv`. Let `mdformat` regenerate the TOC.

- [ ] **Step 2: Resolve `docs/open-topics/T0002-validation-rigor.md`.**

2a. Front-matter `status: partial` → `status: resolved`.

2b. Replace the `## Interpretation caveats` section's intent (now retired) and the `## Suggested next steps` list by appending a `## Resolution` section and trimming next-steps. Concretely: keep `## Done so far`; **remove** the `## Interpretation caveats` and `## Suggested next steps` sections; add:

```markdown
## Resolution

Resolved in iter-11 (spec `docs/specs/00010-deflated-sharpe-pbo-design.md`):

- **Per-recipe PSR** (`cli/experiment/stats.py`): every run reports the
  Probabilistic Sharpe Ratio of its holdout returns (P(true Sharpe > 0),
  corrected for sample length + non-normality) in `cv_results.json`, the report,
  and stdout.
- **`zcrypto rank`**: scans persisted runs as trials and reports the **deflated
  Sharpe ratio** (N-trials correction) of the best trial + **PBO** (CSCV)
  across them, with a ranked table and `runs/rank.json`.
- Both interpretation caveats retired: the CPCV path-Sharpe band is labelled
  *descriptive* (PSR is the significance measure, not the band), and the report's
  holdout marker is relabelled a *different-period (test-window) reference* rather
  than an overfit test (DSR/PBO are the honest overfitting measures). No new data
  was required.
```

- [ ] **Step 3: Move the index entry.** In `docs/open-topics/README.md`, move the `T0002` bullet from `## Partially done` to the end of `## Resolved`, reworded to past tense (e.g. "purged k-fold + embargo + CPCV (iter-9), then per-recipe PSR + the `rank` command's deflated Sharpe + PBO (iter-11) — validation rigor resolved"). Let `mdformat` regenerate the TOC; never hand-edit the `<!-- mdformat-toc -->` block.

- [ ] **Step 4: Append the iter-11 entry to `docs/iterations-history.md`** — a `## 2026-06-18 — iter-11: deflated Sharpe, PBO, and the rank command` section covering: the new `cli/experiment/stats.py` (PSR/DSR/PBO, pure); per-run holdout PSR in `cv_results.json`/report/stdout + the new `returns.csv` artifact; the new top-level `zcrypto rank` command (scans `runs/`, deflated Sharpe + PBO, `runs/rank.json`, the `rank-scan`/`rank-aligned`/`rank-done` log events); the report relabel (descriptive band + different-period holdout marker); and that open-topic `T0002` is resolved — all on existing daily data, no new dependency (scipy already present).

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add README.md docs/open-topics/T0002-validation-rigor.md docs/open-topics/README.md docs/iterations-history.md
git commit -m "docs(experiment): close out iter-11 — README, T0002 resolved, iterations-history"
```

---

## Self-review (against the spec)

- **Spec coverage:** stats module (PSR/DSR/PBO, D1 direct/no-MLFinLab) → Task 1; per-recipe PSR + `returns.csv` (D2/D3) → Task 2; report relabel + PSR + caveat resolution (D4) → Task 3; `rank` command (D5 top-level; on-demand scan of `runs/`; DSR + PBO) → Task 4; `T0002` → resolved + README + iterations-history → Task 5. `cv_results.json` `psr`, `returns.csv`, `runs/rank.json` artifacts all covered.
- **Placeholder scan:** none — complete code for both new files, exact edit anchors for modifications, exact commands.
- **Type consistency:** `sharpe`/`psr`/`expected_max_sharpe`/`deflated_sharpe`/`pbo_cscv` defined in Task 1 are consumed with matching signatures in Task 2 (`psr(holdout_returns)`) and Task 4 (`sharpe`/`psr` per trial, `deflated_sharpe(returns_best, sr_trials)`, `pbo_cscv(matrix, n_splits)`); the `cv` dict gains `holdout_psr` in Task 2 and is read via `cv.get("holdout_psr")` in Task 3; `returns.csv` columns (`date,ret`) written in Task 2 match the reader in Task 4 (`_load_trials`).

## Iterations history

Appending the iter-11 entry to `docs/iterations-history.md` is **Task 5, Step 4** — the final task of this plan (per `.claude/rules/iterations-history.md`).
