# Honest survivorship framing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface a survivorship caveat in every `zcrypto experiment` run (`run_meta.json`, `report.html` title, stdout) — a concise pointer to open-topic `T0005` — so results are read with the right prior; no data, universe, or backtest-logic change.

**Architecture:** One shared wording module (`cli/experiment/caveats.py`) holds a structured `EXPERIMENT_CAVEATS` list (`{topic, summary}` pointers) and a short `SURVIVORSHIP_MARKER`. `command.py` writes the list into `run_meta.json` and prints one stdout line; `report.py` appends the marker to the figure title. `docs/open-topics/*` stays the single source of truth — the surfaces only point to it.

**Tech Stack:** Python 3.12, uv, Typer, plotly; pytest + Typer `CliRunner`.

**Spec:** `docs/specs/00009-survivorship-caveat-design.md`. **Branch:** `feat/survivorship-caveat`.

Run the gate after each task: `uv run ruff check && uv run ruff format --check && uv run pytest -q` (redis-gated tests skip when redis is down; start it with `scripts/redis.sh start`). Commit only on green.

---

## File structure

| File | Responsibility | Task |
| --- | --- | --- |
| `cli/experiment/caveats.py` (new) | The single home for caveat wording: `EXPERIMENT_CAVEATS` (list of `{topic, summary}`) + `SURVIVORSHIP_MARKER` | 1 |
| `cli/experiment/report.py` | Append `SURVIVORSHIP_MARKER` to the figure title as a subtitle | 2 |
| `cli/experiment/command.py` | `run_meta["caveats"] = EXPERIMENT_CAVEATS`; one stdout caveat line | 3 |
| `README.md`, `docs/open-topics/T0005-…`, `docs/iterations-history.md` | Closeout | 4 |

---

## Task 1: Caveats module (`caveats.py`)

**Files:**
- Create: `cli/experiment/caveats.py`
- Test: `tests/test_experiment_caveats.py` (new)

- [ ] **Step 1: Write the failing test** — create `tests/test_experiment_caveats.py`:

```python
def test_experiment_caveats_shape_and_survivorship_present():
    from cli.experiment.caveats import EXPERIMENT_CAVEATS, SURVIVORSHIP_MARKER

    assert isinstance(EXPERIMENT_CAVEATS, list) and EXPERIMENT_CAVEATS
    for c in EXPERIMENT_CAVEATS:
        assert {"topic", "summary"} <= set(c)
        assert c["topic"] and c["summary"]
    assert "T0005" in {c["topic"] for c in EXPERIMENT_CAVEATS}  # survivorship caveat present
    assert isinstance(SURVIVORSHIP_MARKER, str) and SURVIVORSHIP_MARKER.strip()
```

- [ ] **Step 2: Run it, expect FAIL** — `uv run pytest tests/test_experiment_caveats.py -v` → `ModuleNotFoundError: cli.experiment.caveats`.

- [ ] **Step 3: Create `cli/experiment/caveats.py`**:

```python
"""Run-time caveats surfaced in experiment outputs.

These are concise POINTERS to docs/open-topics/* (the single source of truth for
gaps and roadmap). Do not restate a topic's analysis or fix plan here — only a
one-line summary and the topic id a reader follows for the full picture.
"""

SURVIVORSHIP = {
    "topic": "T0005",
    "summary": (
        "universe is survivorship-biased — today's surviving pairs only; "
        "historically-delisted pairs are absent, so the CPCV paths and the holdout "
        "are optimistically inflated (listing dates are respected). "
        "See docs/open-topics/T0005-point-in-time-universe.md."
    ),
}

# All caveats applicable to an experiment run (extend as topics warrant).
EXPERIMENT_CAVEATS = [SURVIVORSHIP]

# Short marker for the report subtitle and the stdout line.
SURVIVORSHIP_MARKER = "survivorship-biased universe — see open-topic T0005"
```

- [ ] **Step 4: Run it, expect PASS** — `uv run pytest tests/test_experiment_caveats.py -v`.

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add cli/experiment/caveats.py tests/test_experiment_caveats.py
git commit -m "feat(experiment): add caveats module (survivorship pointer to open-topic T0005)"
```

---

## Task 2: Report title subtitle (`report.py`)

**Files:**
- Modify: `cli/experiment/report.py` (imports ~line 20; title at line 48)
- Test: `tests/test_experiment_report.py` (append)

- [ ] **Step 1: Write the failing test** — append to `tests/test_experiment_report.py`:

```python
def test_build_report_title_carries_survivorship_marker():
    import types

    import pandas as pd

    from cli.experiment.caveats import SURVIVORSHIP_MARKER
    from cli.experiment.report import build_report

    idx = pd.date_range("2020-01-01", periods=5, freq="D")
    result = types.SimpleNamespace(
        recipe=types.SimpleNamespace(name="t", account=10000.0),
        account_curve=pd.Series(range(5), index=idx, dtype="float64"),
        benchmark_curve=pd.Series(range(5), index=idx, dtype="float64"),
        positions={},
        context_prices={},
    )
    # present in the 3-panel case and the 4-panel (cv) case
    assert SURVIVORSHIP_MARKER in build_report(result).layout.title.text
    cv = {"path_sharpes": [0.2, 0.5], "holdout_sharpe": 0.4}
    assert SURVIVORSHIP_MARKER in build_report(result, cv=cv).layout.title.text
```

- [ ] **Step 2: Run it, expect FAIL** — `uv run pytest tests/test_experiment_report.py::test_build_report_title_carries_survivorship_marker -v` → AssertionError (marker not in title).

- [ ] **Step 3: Edit `cli/experiment/report.py`.**

3a. Add the import after the existing `from cli.experiment.trades import trades_from_positions` line (currently line 20):

```python
from cli.experiment.caveats import SURVIVORSHIP_MARKER
```

(Keep imports sorted per ruff; `caveats` sorts before `stress`/`trades`, so place it accordingly — run `ruff check --fix` if needed.)

3b. Replace the title line (currently line 48):

```python
    title = f"{recipe.name}: {recipe.account:,.0f} → {ending:,.0f} USDT"
```

with:

```python
    title = f"{recipe.name}: {recipe.account:,.0f} → {ending:,.0f} USDT<br><sub>⚠ {SURVIVORSHIP_MARKER}</sub>"
```

- [ ] **Step 4: Run it, expect PASS** — `uv run pytest tests/test_experiment_report.py -v` (the new test + the existing ones).

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add cli/experiment/report.py tests/test_experiment_report.py
git commit -m "feat(experiment): surface survivorship caveat in the report title"
```

---

## Task 3: Command wiring — `run_meta` caveats + stdout line (`command.py`)

**Files:**
- Modify: `cli/experiment/command.py` (module-level import; `run_meta` dict ~line 167-183; stdout block ~line 205-217)
- Test: `tests/test_experiment_command.py` (append, redis-gated)

- [ ] **Step 1: Write the failing test** — append to `tests/test_experiment_command.py` (the `_redis_up`, `runner`, and imports `dataclasses`/`json`/`shutil`/`as_file`/`files`/`pytest` already exist at the top of that file):

```python
@pytest.mark.skipif(not _redis_up(), reason="needs redis (scripts/redis.sh start)")
def test_experiment_emits_survivorship_caveat(tmp_path, monkeypatch):
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
    # --quick is enough: the caveat code path is run-mode-independent, and this keeps the test fast.
    result = runner.invoke(
        app,
        ["experiment", "--recipe", "skeleton", "--data-dir", str(data_dir), "--out", str(out_dir), "--no-open", "--refresh-cache", "--quick"],
    )
    assert result.exit_code == 0, result.output
    bundle = next(iter((out_dir / "skeleton").glob("*")))
    meta = json.loads((bundle / "run_meta.json").read_text())
    assert "T0005" in {c["topic"] for c in meta["caveats"]}  # survivorship caveat recorded
    assert "survivorship" in result.output.lower()  # stdout caveat line printed
```

- [ ] **Step 2: Run it, expect FAIL** — `scripts/redis.sh start` then `uv run pytest tests/test_experiment_command.py::test_experiment_emits_survivorship_caveat -v` → `KeyError: 'caveats'` (or the stdout assertion fails).

- [ ] **Step 3: Edit `cli/experiment/command.py`.**

3a. Add a module-level import (next to the other light imports near the top, e.g. after `from cli.experiment.recipes.base import resolve_recipe`):

```python
from cli.experiment.caveats import EXPERIMENT_CAVEATS, SURVIVORSHIP_MARKER
```

3b. Add the `caveats` key to the `run_meta` dict — insert it immediately after the `"ending_value": result.ending_value,` line inside that dict (currently line 182):

```python
        "ending_value": result.ending_value,
        "caveats": EXPERIMENT_CAVEATS,
```

3c. Add the stdout caveat line immediately **before** the bundle line (currently line 217, `typer.echo(f"  bundle            : {bundle}")`):

```python
    typer.echo(f"⚠ {SURVIVORSHIP_MARKER}")
    typer.echo(f"  bundle            : {bundle}")
```

(The caveat echo is unconditional — it prints in both the default and `--quick` runs.)

- [ ] **Step 4: Run it, expect PASS** — `uv run pytest tests/test_experiment_command.py::test_experiment_emits_survivorship_caveat -v`.

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add cli/experiment/command.py tests/test_experiment_command.py
git commit -m "feat(experiment): record survivorship caveat in run_meta and stdout"
```

---

## Task 4: Closeout — README, `T0005` update, iterations-history

**Files:**
- Modify: `README.md` (`## Usage` → experiment section)
- Modify: `docs/open-topics/T0005-point-in-time-universe.md`
- Modify: `docs/iterations-history.md`

- [ ] **Step 1: README `## Usage`.** In the `zcrypto experiment` subsection, add one sentence: "Every run emits a survivorship caveat (universe is today's surviving pairs; delisted pairs absent) — shown in the report title and stdout, and recorded under `caveats` in `run_meta.json`; see open-topic `T0005`." Let `mdformat` regenerate the TOC; do not hand-edit the `<!-- mdformat-toc -->` block.

- [ ] **Step 2: Update `docs/open-topics/T0005-point-in-time-universe.md`** (stays `status: open`).

2a. Append this paragraph to the end of the `## Findings so far` section:

```markdown

Reality check (iter-10): the **listing side is already handled** — qlib returns
rows only where data exists, so a pair is never traded before it listed; the bias
is the **universe selection** (today's survivors). We hold **zero delisted-pair
data**, and `zcrypto data delist` *deletes* a pair's history (`cli/data/pipeline.py`),
so a real fix must first acquire historically-delisted pairs. iter-10 added an
honest survivorship caveat to the experiment outputs (report title, stdout,
`run_meta.json` `caveats`) but changed no results.
```

2b. Replace the `## Suggested next steps` list with the sharpened roadmap:

```markdown
## Suggested next steps

- Acquire historically-delisted Binance USDT pairs' data (enumerate
  `data.binance.vision` for symbols whose daily-kline archives end before today)
  so the panel is survivorship-free.
- Change `zcrypto data delist` to retain-with-end-date (or keep a delisted
  registry) instead of deleting history.
- Build point-in-time membership over the expanded panel (qlib market-name
  instruments file honoring per-symbol listing/delist dates) and feed it to the
  experiment.
- Add a delisting-loss assumption (forced liquidation at the last close / a
  size-scaled haircut).
- Re-measure the baseline's edge under the point-in-time universe vs the current
  survivor universe.
```

- [ ] **Step 3: Append the iter-10 entry to `docs/iterations-history.md`** — a new `## 2026-06-18 — iter-10: honest survivorship framing` section with bullets covering: a new `cli/experiment/caveats.py` holding `EXPERIMENT_CAVEATS` (`{topic, summary}` pointers) + `SURVIVORSHIP_MARKER`; the survivorship caveat now surfaces in the report title, stdout, and `run_meta.json` `caveats` (both default and `--quick`); `docs/open-topics/*` remains the single source of truth (the surfaces only point to `T0005`); `T0005` re-scoped to the data-acquisition reality; and the two iter-9 CPCV interpretation caveats captured in `T0002` (with a next-step to surface them later). Note this iteration changed no data/universe/backtest logic.

- [ ] **Step 4: Gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
git add README.md docs/open-topics/T0005-point-in-time-universe.md docs/iterations-history.md
git commit -m "docs(experiment): close out iter-10 — README usage, T0005 re-scope, iterations-history"
```

---

## Self-review (against the spec)

- **Spec coverage:** caveats.py (`EXPERIMENT_CAVEATS`/`SURVIVORSHIP_MARKER`) → Task 1; report subtitle → Task 2; `run_meta` caveats + stdout line → Task 3; SSOT (pointers only, no roadmap duplication) → honored across Tasks 1/3 (summary references the topic; no roadmap text outside `T0005`); survivorship-only scope → only the `T0005` caveat is defined; `T0005` re-scope + README + iterations-history → Task 4. CPCV-interpretation caveats already captured in `T0002` in the spec commit (out of this plan's scope).
- **Placeholder scan:** none — every step has concrete code/text and exact commands.
- **Type consistency:** `EXPERIMENT_CAVEATS` (list of `{topic, summary}`) and `SURVIVORSHIP_MARKER` (str) are defined in Task 1 and consumed identically in Tasks 2 (marker → title) and 3 (list → run_meta, marker → stdout); the test in Task 1 pins the shape the consumers rely on.

## Iterations history

Appending the iter-10 entry to `docs/iterations-history.md` is **Task 4, Step 3** — the final task of this plan (per `.claude/rules/iterations-history.md`).
