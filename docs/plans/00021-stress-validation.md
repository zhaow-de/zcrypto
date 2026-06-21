# Walk-forward OOS Validation (`stress` harness) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `zcrypto stress` subcommand that validates a recipe out-of-sample by rolling the train→test split across annual OOS windows (each trained only on prior data) and reporting the per-window long-only `sharpe` vs market-neutral `ls_sharpe` — to confirm or refute whether the iter-21 L/S edge holds beyond the dev-seen 2025 holdout.

**Architecture:** A pure window builder (`cli/stress/windows.py`) produces leak-safe `(train, test)` segment spans; the `cli/stress/command.py` subcommand loops them, `dataclasses.replace`s each onto the recipe's `segments`, and calls the iter-21 `run_holdout_seeds` per window (which already returns per-seed `sharpe` + `ls_sharpe`), then prints a per-window summary table and writes `stress_summary.json`. No new modeling code — the window grid is the only new logic.

**Tech Stack:** Python 3.12, uv, Typer, qlib, pandas, pytest + Typer `CliRunner`, ruff.

## Global Constraints

- **No new modeling/holdout code** — per window, build a segment-shifted recipe via `dataclasses.replace(recipe, segments=…)` and call the EXISTING `run_holdout_seeds(recipe, *, data_dir, seeds, deterministic)` (returns `{"per_seed": [...], "summary": {...}}` where each per-seed dict carries `sharpe` (long-only) + `ls_sharpe` (market-neutral) + `ending_value`/`ls_ending`/`psr`/`max_drawdown`; `summary` aggregates all keys).
- **Leak-safe windows:** `train = [data_start, test_start − purge_days]`, `test = [test_start, test_end]`; `purge_days = 8` (≥ the `label_horizon_days`=6, so the 5-day-ahead label can't leak train→test). `train_start` is always `data_start` (expanding). The LAST window's `test_end` = `data_end`; earlier windows' `test_end` = (next test_start − 1 day).
- **Default grid:** `test_starts = ["2022-01-01", "2023-01-01", "2024-01-01", "2025-01-01"]`; `data_start`/`data_end` read from the dataset index (`load_index(data_dir).calendar.from_date`/`.to_date`). So `oos_2025` test = `2025-01-01..<data_end>` (reproduces the iter-21 holdout as one of the four).
- **`run_holdout_seeds` reads only `segments["train"]` + `segments["test"]`** (the light multi-seed path ignores `valid`) — but the segments dict must still carry a well-formed `valid` (set inside the purge gap).
- **Deterministic:** the subcommand calls `run_holdout_seeds(..., deterministic=True)` so the OOS validation is reproducible.
- ruff: line length 132, double quotes, import sorting (`select = ["I"]`). Run `uv run ruff check --fix <files>` + `uv run ruff format <files>` before each commit.
- Commit messages: `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: `build_oos_windows` pure window builder

**Files:**
- Create: `cli/stress/__init__.py` (empty), `cli/stress/windows.py`
- Test: `tests/test_stress_windows.py`

**Interfaces:**
- Produces: `PURGE_DAYS: int = 8`; `build_oos_windows(test_starts: list[str], *, data_start: str, data_end: str, purge_days: int = PURGE_DAYS) -> list[dict]` — each dict `{"label": str, "train": (str, str), "valid": (str, str), "test": (str, str)}`, ISO date strings. Consumed by Task 2.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stress_windows.py`:

```python
import datetime as dt

from cli.stress.windows import PURGE_DAYS, build_oos_windows

_STARTS = ["2022-01-01", "2023-01-01", "2024-01-01", "2025-01-01"]


def _w():
    return build_oos_windows(_STARTS, data_start="2020-01-01", data_end="2026-06-15")


def test_one_window_per_test_start_labeled_by_year():
    w = _w()
    assert [x["label"] for x in w] == ["oos_2022", "oos_2023", "oos_2024", "oos_2025"]


def test_train_always_starts_at_data_start_expanding():
    assert all(x["train"][0] == "2020-01-01" for x in _w())


def test_train_ends_purge_days_before_test_start_leak_safe():
    for x in _w():
        train_end = dt.date.fromisoformat(x["train"][1])
        test_start = dt.date.fromisoformat(x["test"][0])
        assert (test_start - train_end).days == PURGE_DAYS  # strictly before, by the purge


def test_test_windows_are_contiguous_annual_last_to_data_end():
    w = _w()
    assert w[0]["test"] == ("2022-01-01", "2022-12-31")
    assert w[1]["test"] == ("2023-01-01", "2023-12-31")
    assert w[2]["test"] == ("2024-01-01", "2024-12-31")
    assert w[3]["test"] == ("2025-01-01", "2026-06-15")  # last → data_end (the iter-21 holdout)


def test_valid_sits_inside_the_purge_gap():
    for x in _w():
        vs, ve = dt.date.fromisoformat(x["valid"][0]), dt.date.fromisoformat(x["valid"][1])
        train_end = dt.date.fromisoformat(x["train"][1])
        test_start = dt.date.fromisoformat(x["test"][0])
        assert train_end < vs <= ve < test_start  # valid strictly between train and test
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_stress_windows.py -v`
Expected: FAIL — `ModuleNotFoundError: cli.stress.windows`.

- [ ] **Step 3: Implement `cli/stress/__init__.py` (empty) and `cli/stress/windows.py`**

`cli/stress/__init__.py`: empty file.

`cli/stress/windows.py`:

```python
"""Out-of-sample walk-forward window grid for `zcrypto stress` (see docs/specs/00021).

Each window trains only on data strictly before its test period (expanding from data_start),
with a purge gap >= the label horizon so the forward-looking label cannot leak train -> test.
Pure / qlib-free so the leak-safe window math is unit-testable in isolation.
"""

from __future__ import annotations

import datetime as dt

PURGE_DAYS: int = 8  # >= label_horizon_days (6); the gap between train_end and test_start


def build_oos_windows(
    test_starts: list[str],
    *,
    data_start: str,
    data_end: str,
    purge_days: int = PURGE_DAYS,
) -> list[dict]:
    """Build OOS walk-forward windows from annual test-start dates.

    For each `test_start`: train = [data_start, test_start - purge_days]; test = [test_start,
    (next test_start - 1 day) or data_end for the last]; valid = the purge gap (ignored by the
    multi-seed light holdout, kept well-formed). Returns one dict per window in order.
    """
    starts = sorted(test_starts)
    windows: list[dict] = []
    for i, ts in enumerate(starts):
        ts_d = dt.date.fromisoformat(ts)
        train_end = ts_d - dt.timedelta(days=purge_days)
        if i + 1 < len(starts):
            test_end = dt.date.fromisoformat(starts[i + 1]) - dt.timedelta(days=1)
        else:
            test_end = dt.date.fromisoformat(data_end)
        windows.append(
            {
                "label": f"oos_{ts_d.year}",
                "train": (data_start, train_end.isoformat()),
                "valid": ((train_end + dt.timedelta(days=1)).isoformat(), (ts_d - dt.timedelta(days=1)).isoformat()),
                "test": (ts, test_end.isoformat()),
            }
        )
    return windows
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_stress_windows.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix cli/stress/__init__.py cli/stress/windows.py tests/test_stress_windows.py
uv run ruff format cli/stress/windows.py tests/test_stress_windows.py
git add cli/stress/__init__.py cli/stress/windows.py tests/test_stress_windows.py
git commit -m "feat(stress): add OOS walk-forward window builder"
```

---

### Task 2: `zcrypto stress` subcommand

**Files:**
- Create: `cli/stress/command.py`
- Modify: `cli/__main__.py` (register the subcommand), `README.md` (Usage)
- Test: `tests/test_stress_command.py`

**Interfaces:**
- Consumes: `build_oos_windows` (Task 1); `run_holdout_seeds` (`cli.experiment.multiseed`); `resolve_recipe` (`cli.experiment.recipes.base`); `load_config`/`resolve_data_dir` (`cli.config`); `load_index` (`cli.data.index`).
- Produces: `stress(recipe_name, seeds, data_dir, out)` Typer command, registered as `zcrypto stress`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stress_command.py`:

```python
import json
from pathlib import Path

from typer.testing import CliRunner

from cli.__main__ import app

runner = CliRunner()


def _fake_holdout(seen):
    # capture each window's (train, test) and return a fixed summary with sharpe + ls_sharpe.
    def _f(recipe, *, data_dir, seeds, deterministic=False):
        seen.append((recipe.segments["train"], recipe.segments["test"]))
        return {
            "per_seed": [{"seed": 1, "sharpe": -0.5, "ls_sharpe": 0.4}],
            "summary": {
                "sharpe": {"mean": -0.5, "std": 0.0, "min": -0.5, "max": -0.5, "n": 1},
                "ls_sharpe": {"mean": 0.4, "std": 0.0, "min": 0.4, "max": 0.4, "n": 1},
            },
        }
    return _f


def _patch(monkeypatch, tmp_path, seen):
    import cli.stress.command as cmd

    class _Recipe:
        name = "steady"
        segments = {"train": ("2020-01-01", "2023-12-31"), "valid": ("2024-01-01", "2024-12-31"), "test": ("2025-01-01", "2026-06-15")}
        label_horizon_days = 6

    class _Idx:
        class calendar:
            from_date = "2020-01-01"
            to_date = "2026-06-15"

    monkeypatch.setattr(cmd, "resolve_recipe", lambda name: _Recipe())
    monkeypatch.setattr(cmd, "load_config", lambda: {})
    monkeypatch.setattr(cmd, "resolve_data_dir", lambda d, cfg: tmp_path)
    monkeypatch.setattr(cmd, "load_index", lambda d: _Idx())
    monkeypatch.setattr(cmd, "run_holdout_seeds", _fake_holdout(seen))


def test_stress_loops_all_windows_and_writes_summary(monkeypatch, tmp_path):
    seen = []
    _patch(monkeypatch, tmp_path, seen)
    out = tmp_path / "runs"
    result = runner.invoke(app, ["stress", "--recipe", "steady", "--seeds", "1", "--out", str(out)])

    assert result.exit_code == 0, result.stdout
    # 4 OOS windows, each trained from 2020 only on prior data
    assert len(seen) == 4
    assert all(tr[0] == "2020-01-01" for tr, _te in seen)
    assert [te for _tr, te in seen] == [
        ("2022-01-01", "2022-12-31"), ("2023-01-01", "2023-12-31"),
        ("2024-01-01", "2024-12-31"), ("2025-01-01", "2026-06-15"),
    ]
    # summary json written with one entry per window
    sj = sorted(out.glob("stress/steady/*/stress_summary.json"))
    assert sj, "stress_summary.json not written"
    data = json.loads(sj[-1].read_text())
    assert [w["label"] for w in data["windows"]] == ["oos_2022", "oos_2023", "oos_2024", "oos_2025"]
    assert data["windows"][0]["ls_sharpe_mean"] == 0.4
    # the per-window table is printed
    assert "oos_2022" in result.stdout and "ls_sharpe" in result.stdout.lower()


def test_stress_unknown_recipe_exits_nonzero(monkeypatch, tmp_path):
    import cli.stress.command as cmd

    def _raise(name):
        raise ValueError("Recipe 'nope' not found. Available: steady")

    monkeypatch.setattr(cmd, "resolve_recipe", _raise)
    result = runner.invoke(app, ["stress", "--recipe", "nope"])
    assert result.exit_code == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_stress_command.py -v`
Expected: FAIL — no `stress` command registered (exit code 2 / usage error).

- [ ] **Step 3: Implement `cli/stress/command.py`**

```python
"""`zcrypto stress` — walk-forward OOS validation across annual test windows."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Optional

import typer

from cli.config import ConfigError, load_config, resolve_data_dir
from cli.data.index import load_index
from cli.experiment.multiseed import run_holdout_seeds
from cli.experiment.recipes.base import resolve_recipe
from cli.stress.windows import build_oos_windows

_TEST_STARTS = ["2022-01-01", "2023-01-01", "2024-01-01", "2025-01-01"]


def stress(
    recipe_name: str = typer.Option("steady", "--recipe", help="Recipe to validate out-of-sample."),
    seeds: int = typer.Option(8, "--seeds", help="Seeds per OOS window (multi-seed holdout).", min=1),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", help="Qlib provider dir; defaults to zcrypto.toml."),  # noqa: UP007
    out: Path = typer.Option(Path("runs"), "--out", help="Root for stress bundles (<out>/stress/<recipe>/<ts>)."),
) -> None:
    """Roll train→test across annual OOS windows; report per-window long-only vs L/S Sharpe."""
    import json
    from datetime import datetime, timezone

    from cli.logging import get_logger

    logger = get_logger("stress.command")

    try:
        recipe = resolve_recipe(recipe_name)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    try:
        data_dir = resolve_data_dir(data_dir, load_config()).resolve()
    except ConfigError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    idx = load_index(data_dir)
    if idx is None:
        typer.echo(f"ERROR: no dataset index at {data_dir}", err=True)
        raise typer.Exit(code=1)

    windows = build_oos_windows(_TEST_STARTS, data_start=idx.calendar.from_date, data_end=idx.calendar.to_date)

    results = []
    for w in windows:
        recipe_w = dataclasses.replace(recipe, segments={"train": w["train"], "valid": w["valid"], "test": w["test"]})
        logger.info("stress-window", extra={"label": w["label"], "train": w["train"], "test": w["test"]})
        res = run_holdout_seeds(recipe_w, data_dir=data_dir, seeds=seeds, deterministic=True)
        s = res["summary"]
        results.append(
            {
                "label": w["label"],
                "train": w["train"],
                "test": w["test"],
                "sharpe_mean": s["sharpe"]["mean"],
                "ls_sharpe_mean": s["ls_sharpe"]["mean"],
                "ls_sharpe_min": s["ls_sharpe"]["min"],
            }
        )

    created = datetime.now(timezone.utc)
    bundle = out / "stress" / recipe.name / created.strftime("%Y%m%dT%H%M%SZ")
    bundle.mkdir(parents=True, exist_ok=True)
    ls_means = [r["ls_sharpe_mean"] for r in results]
    aggregate = {
        "n_windows": len(results),
        "ls_sharpe_windows_positive": sum(1 for v in ls_means if v > 0),
        "ls_sharpe_worst": min(ls_means) if ls_means else None,
        "ls_sharpe_mean_across_windows": (sum(ls_means) / len(ls_means)) if ls_means else None,
    }
    (bundle / "stress_summary.json").write_text(
        json.dumps({"recipe": recipe.name, "seeds": seeds, "windows": results, "aggregate": aggregate}, indent=2)
    )

    typer.echo(f"OOS walk-forward — {recipe.name} ({seeds} seeds/window)")
    typer.echo(f"  {'window':10} {'long-only sharpe':>17} {'L/S sharpe':>11}")
    for r in results:
        typer.echo(f"  {r['label']:10} {r['sharpe_mean']:>17.3f} {r['ls_sharpe_mean']:>11.3f}")
    typer.echo(
        f"  L/S Sharpe: {aggregate['ls_sharpe_windows_positive']}/{aggregate['n_windows']} windows positive; "
        f"worst {aggregate['ls_sharpe_worst']:.3f}; mean {aggregate['ls_sharpe_mean_across_windows']:.3f}"
    )
    typer.echo(f"  bundle: {bundle}")
```

- [ ] **Step 4: Register the subcommand in `cli/__main__.py`**

After the `rank` registration block (and before the `data_app` add_typer), add:

```python
from cli.stress.command import stress

app.command(name="stress")(stress)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_stress_command.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Update README Usage**

In `README.md` `## Usage`, add a `zcrypto stress` subsection: purpose (walk-forward OOS validation — per-window long-only vs market-neutral L/S Sharpe across annual windows trained only on prior data), synopsis `zcrypto stress [--recipe steady] [--seeds 8] [--data-dir ./data] [--out ./runs]`, and a one-line note that it reuses the multi-seed holdout per window and writes `stress_summary.json`. Don't hand-edit the mdformat TOC.

- [ ] **Step 7: Lint + targeted suite + commit**

```bash
uv run ruff check --fix cli/stress/command.py cli/__main__.py tests/test_stress_command.py
uv run ruff format cli/stress/command.py cli/__main__.py tests/test_stress_command.py
uv run pytest tests/test_stress_windows.py tests/test_stress_command.py -q
git add cli/stress/command.py cli/__main__.py tests/test_stress_command.py README.md
git commit -m "feat(stress): add zcrypto stress walk-forward OOS subcommand"
```

Expected: the targeted suite passes.

---

## Closeout (operational — run by the orchestrator after Tasks 1-2 land, NOT a subagent task)

1. **Run the validation** (redis up via `scripts/redis.sh start`): `uv run zcrypto stress --recipe steady --seeds 8` and `uv run zcrypto stress --recipe funding_steady --seeds 8`. Each prints the per-window table + writes `stress_summary.json`.
2. **Compute the verdict** from the per-window `ls_sharpe`:
   - Is the **market-neutral L/S** Sharpe positive/consistent across the OOS windows — *especially the 2022 crisis window* (`oos_2022`)? → the iter-21 edge is **validated** (and `T0016` is green-lit) or **overfit** (T0016 stays gated, and that's the finding).
   - Does `funding_steady` differ from `steady` OOS? → confirms (OOS) the iter-21 "funding doesn't help market-neutral" finding.
3. **Advance `T0007` → `partial`:** `## Done so far` = the OOS walk-forward validation harness (`zcrypto stress`) + the verdict; trim `## Suggested next steps` to the parked training-window grid (gated on acquiring pre-2020 data).
4. **Note the `T0016` disposition** (green-lit vs still-gated) in the iter-22 history + the verdict.
5. **README `## Usage`:** confirm the `zcrypto stress` subcommand is documented (Task 2).
6. **iter-22 iterations-history entry:** the `stress` harness + the OOS validation verdict.

---

## Self-Review

**Spec coverage:** Decision 1 (reuse `run_holdout_seeds` per window) → Task 2; Decision 2 (annual grid, expanding train, purge ≥ label horizon) → Task 1 (`build_oos_windows`) + the window tests; Decision 3 (pure builder) → Task 1; Decision 4 (`zcrypto stress` subcommand + table + `stress_summary.json`) → Task 2; Decision 5 (verdict) → Closeout 2. README → Task 2; T0007 advance + T0016 disposition + iter-22 history → Closeout 3-6.

**Placeholder scan:** No TBD/TODO. All code steps carry full code; the window grid + purge are concrete. Verdict values are correctly closeout (the runs).

**Type consistency:** `build_oos_windows(test_starts, *, data_start, data_end, purge_days=PURGE_DAYS) -> list[{label,train,valid,test}]` identical across Task 1 code, Task 1 tests, and Task 2's call. `run_holdout_seeds(recipe, *, data_dir, seeds, deterministic)` → `{"summary": {"sharpe": {...}, "ls_sharpe": {...}}}` matches the iter-21 contract used in Task 2 + the test's fake. The `stress` command reads `idx.calendar.from_date`/`.to_date` (matches `load_index`'s `IndexData` shape). `_TEST_STARTS` default matches the spec grid.
