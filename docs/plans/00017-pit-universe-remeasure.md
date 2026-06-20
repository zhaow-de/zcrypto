# PIT Universe + Survivorship Re-measure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--pit-universe` flag to `zcrypto experiment` that expands any recipe's universe to point-in-time membership (the ever-top-25 delisted/faded majors), flipping the run's survivorship caveat, so all recipes can be re-measured survivorship-free — resolving `T0005`.

**Architecture:** A frozen `Recipe` carries a `universe` tuple that every downstream stage (`run_cpcv`/`run_experiment`/`run_holdout_seeds`) reads transparently. So the flag's whole mechanism is: swap the recipe's universe **once at the top** of the command via `dataclasses.replace` (no threading through cpcv/scaffold/multiseed), and pick the survivorship-vs-PIT caveat + report/stdout marker from the same boolean. Delisting-loss needs no code — the recon proved qlib's default position-freeze captures the mark-to-market loss. Terra LUNA acquisition + the actual re-measure are operational closeout steps (no new code).

**Tech Stack:** Python 3.12, uv, Typer, qlib, pytest + Typer `CliRunner`, ruff.

## Global Constraints

- **Survivor path is byte-identical when the flag is off.** `--pit-universe` defaults to `False`; with it off, the recipe, caveats, marker, and every downstream call are exactly as today. Tests must assert this.
- **DRY — swap the universe once, no threading.** Expand via `dataclasses.replace(recipe, universe=…)` right after `resolve_recipe`; do NOT add a `pit_universe`/universe parameter to `run_cpcv`, `run_experiment`, `run_holdout_seeds`, `handler_config`, or the scaffold. They read `recipe.universe` and must stay unchanged.
- **`PIT_ADDITIONS` exact symbols (10, verified against `data/instruments/all.txt`):** `DASHUSDT, ZECUSDT, QTUMUSDT, ICXUSDT, FTTUSDT, WAVESUSDT, OMGUSDT, XEMUSDT, BTGUSDT, NANOUSDT`. **`LUNCUSDT` is NOT in the coded constant** — it is appended at closeout once the Terra acquisition lands, so a `--pit-universe` run between merge and closeout never references an absent instrument.
- **Universe merge is order-preserving and de-duplicated** (`dict.fromkeys`) — survivors first, additions appended, no symbol twice.
- **ruff:** line length 132, double quotes, import sorting (`select = ["I"]`). Run `uv run ruff check --fix && uv run ruff format` before each commit.
- **Commit messages:** `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: `PIT_ADDITIONS` constant + `with_pit_universe` helper

**Files:**
- Modify: `cli/experiment/recipes/base.py` (add the `replace` import, the constant, the helper)
- Test: `tests/test_experiment_recipe.py`

**Interfaces:**
- Produces: `PIT_ADDITIONS: tuple[str, ...]` (the 10 majors) and `with_pit_universe(recipe: Recipe) -> Recipe` (returns a copy with `universe = recipe.universe + PIT_ADDITIONS`, deduped, order-preserving). Task 3 consumes both.

- [ ] **Step 1: Write the failing tests**

In `tests/test_experiment_recipe.py`, add:

```python
def test_pit_additions_are_the_ten_delisted_faded_majors():
    from cli.experiment.recipes.base import PIT_ADDITIONS

    assert PIT_ADDITIONS == (
        "DASHUSDT", "ZECUSDT", "QTUMUSDT", "ICXUSDT", "FTTUSDT",
        "WAVESUSDT", "OMGUSDT", "XEMUSDT", "BTGUSDT", "NANOUSDT",
    )
    # LUNCUSDT is appended at closeout, not in the coded constant
    assert "LUNCUSDT" not in PIT_ADDITIONS


def test_with_pit_universe_appends_additions_order_preserving():
    from cli.experiment.recipes.base import PIT_ADDITIONS, resolve_recipe, with_pit_universe

    base = resolve_recipe("steady")
    pit = with_pit_universe(base)

    # frozen original untouched
    assert "NANOUSDT" not in base.universe
    # survivors kept first, in order; additions appended
    assert pit.universe[: len(base.universe)] == base.universe
    assert pit.universe[len(base.universe):] == PIT_ADDITIONS
    # only the universe changed
    import dataclasses
    assert dataclasses.replace(pit, universe=base.universe) == base


def test_with_pit_universe_dedups_overlap():
    import dataclasses

    from cli.experiment.recipes.base import resolve_recipe, with_pit_universe

    base = dataclasses.replace(resolve_recipe("steady"), universe=resolve_recipe("steady").universe + ("NANOUSDT",))
    pit = with_pit_universe(base)
    assert pit.universe.count("NANOUSDT") == 1
    assert len(pit.universe) == len(set(pit.universe))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_experiment_recipe.py -k "pit" -v`
Expected: FAIL — `ImportError: cannot import name 'PIT_ADDITIONS'` / `with_pit_universe`.

- [ ] **Step 3: Implement the constant + helper**

In `cli/experiment/recipes/base.py`, change the dataclasses import (line 6) to add `replace`:

```python
from dataclasses import dataclass, field, replace
```

Then add, after the `Recipe` class (after line 53, before `resolve_recipe`):

```python
# Point-in-time universe additions (see docs/specs/00017). These ever-top-25 USDT majors
# blew up (NANO/BTG/OMG/WAVES/XEM delisted) or faded out of today's survivor universe while
# still listed (DASH/FTT/ICX/QTUM/ZEC); iter-16 acquired all 10 archive-only with real
# listing/delisting ranges. Appending them to a recipe's universe (the --pit-universe flag)
# makes a run survivorship-free — qlib trades each only within its real range. The Terra
# blow-up LUNCUSDT is appended here at the iter-18 closeout, once the capped
# LUNAUSDT->LUNCUSDT acquisition lands (kept out until then so a flagged run never
# references an instrument absent from the dataset).
PIT_ADDITIONS: tuple[str, ...] = (
    "DASHUSDT",
    "ZECUSDT",
    "QTUMUSDT",
    "ICXUSDT",
    "FTTUSDT",
    "WAVESUSDT",
    "OMGUSDT",
    "XEMUSDT",
    "BTGUSDT",
    "NANOUSDT",
)


def with_pit_universe(recipe: Recipe) -> Recipe:
    """Return a copy of *recipe* with its universe expanded to point-in-time membership.

    Appends :data:`PIT_ADDITIONS` to ``recipe.universe``, de-duplicated and order-preserving
    (survivors first). Every downstream stage reads ``recipe.universe``, so swapping it here
    threads the PIT universe through cpcv/scaffold/multiseed with no other change.
    """
    merged = tuple(dict.fromkeys(recipe.universe + PIT_ADDITIONS))
    return replace(recipe, universe=merged)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_experiment_recipe.py -k "pit" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix cli/experiment/recipes/base.py tests/test_experiment_recipe.py
uv run ruff format cli/experiment/recipes/base.py tests/test_experiment_recipe.py
git add cli/experiment/recipes/base.py tests/test_experiment_recipe.py
git commit -m "feat(experiment): add PIT_ADDITIONS + with_pit_universe helper"
```

---

### Task 2: point-in-time caveat + marker; `build_report` marker param

**Files:**
- Modify: `cli/experiment/caveats.py` (add `POINT_IN_TIME` + `PIT_MARKER`)
- Modify: `cli/experiment/report.py:30,51` (`build_report` gains a `marker` kwarg)
- Test: `tests/test_experiment_caveats.py`, `tests/test_experiment_report.py`

**Interfaces:**
- Produces: `POINT_IN_TIME: dict` (a caveat dict like `SURVIVORSHIP`), `PIT_MARKER: str`, and `build_report(result, *, stress_windows=None, cv=None, marker=SURVIVORSHIP_MARKER)`. Task 3 consumes `POINT_IN_TIME`, `PIT_MARKER`, and the new `marker=` kwarg.

- [ ] **Step 1: Write the failing tests**

In `tests/test_experiment_caveats.py`, add:

```python
def test_point_in_time_caveat_points_to_t0005():
    from cli.experiment.caveats import POINT_IN_TIME

    assert POINT_IN_TIME["topic"] == "T0005"
    assert "survivorship-free" in POINT_IN_TIME["summary"]
    assert "T0005-point-in-time-universe.md" in POINT_IN_TIME["summary"]


def test_pit_marker_says_survivorship_free():
    from cli.experiment.caveats import PIT_MARKER, SURVIVORSHIP_MARKER

    assert "survivorship-free" in PIT_MARKER
    assert PIT_MARKER != SURVIVORSHIP_MARKER
```

In `tests/test_experiment_report.py`, add (reusing the existing `_make_result()` helper):

```python
def test_build_report_default_marker_is_survivorship():
    from cli.experiment.caveats import SURVIVORSHIP_MARKER

    fig = build_report(_make_result())
    assert SURVIVORSHIP_MARKER in fig.layout.title.text


def test_build_report_marker_override():
    from cli.experiment.caveats import PIT_MARKER

    fig = build_report(_make_result(), marker=PIT_MARKER)
    assert PIT_MARKER in fig.layout.title.text
    assert "survivorship-biased" not in fig.layout.title.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_experiment_caveats.py tests/test_experiment_report.py -k "point_in_time or pit_marker or marker" -v`
Expected: FAIL — `ImportError` for `POINT_IN_TIME`/`PIT_MARKER`; `build_report() got an unexpected keyword argument 'marker'`.

- [ ] **Step 3: Implement the caveat, marker, and the `build_report` kwarg**

In `cli/experiment/caveats.py`, after `SURVIVORSHIP` (after line 16), add:

```python
POINT_IN_TIME = {
    "topic": "T0005",
    "summary": (
        "point-in-time universe — historically delisted/faded majors are included over their "
        "real listing ranges, so the run is survivorship-free. Delisting-loss is captured by "
        "qlib's position freeze at the last close (frozen capital is not redeployed — a "
        "conservative imperfection). See docs/open-topics/T0005-point-in-time-universe.md."
    ),
}
```

And after `SURVIVORSHIP_MARKER` (after line 22), add:

```python
# Marker for the report subtitle + stdout line when --pit-universe is on (the run is
# survivorship-free, so the SURVIVORSHIP_MARKER above must not appear).
PIT_MARKER = "point-in-time universe (survivorship-free) — see open-topic T0005"
```

In `cli/experiment/report.py`, change the signature (line 30):

```python
def build_report(result, *, stress_windows=None, cv=None, marker=SURVIVORSHIP_MARKER) -> go.Figure:
```

and the title line (line 51) to use `marker`:

```python
    title = f"{recipe.name}: {recipe.account:,.0f} → {ending:,.0f} USDT<br><sub>⚠ {marker}</sub>"
```

(`report.py` already imports `SURVIVORSHIP_MARKER` at line 20, so the default resolves.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_experiment_caveats.py tests/test_experiment_report.py -v`
Expected: PASS (the 4 new tests + the existing report/caveats tests unchanged).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix cli/experiment/caveats.py cli/experiment/report.py tests/test_experiment_caveats.py tests/test_experiment_report.py
uv run ruff format cli/experiment/caveats.py cli/experiment/report.py tests/test_experiment_caveats.py tests/test_experiment_report.py
git add cli/experiment/caveats.py cli/experiment/report.py tests/test_experiment_caveats.py tests/test_experiment_report.py
git commit -m "feat(experiment): add point-in-time caveat + marker; build_report marker kwarg"
```

---

### Task 3: `--pit-universe` flag wiring + README

**Files:**
- Modify: `cli/experiment/command.py` (imports, the flag, the recipe swap + caveat/marker selection, three use-sites)
- Modify: `README.md` (the `experiment` Usage section)
- Test: `tests/test_experiment_command.py`

**Interfaces:**
- Consumes: `with_pit_universe` (Task 1); `POINT_IN_TIME`, `PIT_MARKER` (Task 2); the `marker=` kwarg on `build_report` (Task 2).

- [ ] **Step 1: Write the failing tests**

In `tests/test_experiment_command.py`: first extend `_patch_experiment_heavy_fns` so the `fake_run_experiment` captures the recipe's universe — add this line inside that fake (alongside the existing `captured["run_experiment_kwargs"] = …`):

```python
        captured["run_experiment_recipe_universe"] = tuple(recipe.universe)
```

Then add two tests (follow the existing `test_experiment_passes_seeds_and_deterministic` setup — a `short_recipe` via monkeypatched `resolve_recipe`, `_patch_experiment_heavy_fns`, `--quick` to skip CPCV):

```python
def test_experiment_pit_universe_expands_and_flips_marker(monkeypatch, tmp_path):
    """--pit-universe expands the universe with PIT_ADDITIONS and flips the marker."""
    from cli.experiment.caveats import PIT_MARKER
    from cli.experiment.recipes.base import PIT_ADDITIONS

    captured = {}
    short_recipe = _short_recipe()  # same helper/inline recipe the seeds test uses
    monkeypatch.setattr("cli.experiment.command.resolve_recipe", lambda name: short_recipe)
    monkeypatch.setattr("cli.experiment.command.load_config", lambda: {})
    monkeypatch.setattr("cli.experiment.command.resolve_data_dir", lambda d, cfg: tmp_path)
    _patch_experiment_heavy_fns(monkeypatch, tmp_path, captured, _fake_result())

    result = runner.invoke(
        app, ["experiment", "--recipe", "steady", "--quick", "--pit-universe", "--out", str(tmp_path / "runs")]
    )

    assert result.exit_code == 0, result.stdout
    uni = captured["run_experiment_recipe_universe"]
    assert uni[: len(short_recipe.universe)] == short_recipe.universe  # survivors kept
    for sym in PIT_ADDITIONS:
        assert sym in uni
    assert PIT_MARKER in result.stdout


def test_experiment_default_universe_is_survivor(monkeypatch, tmp_path):
    """Without --pit-universe the universe and marker are unchanged (byte-identical path)."""
    from cli.experiment.caveats import SURVIVORSHIP_MARKER
    from cli.experiment.recipes.base import PIT_ADDITIONS

    captured = {}
    short_recipe = _short_recipe()
    monkeypatch.setattr("cli.experiment.command.resolve_recipe", lambda name: short_recipe)
    monkeypatch.setattr("cli.experiment.command.load_config", lambda: {})
    monkeypatch.setattr("cli.experiment.command.resolve_data_dir", lambda d, cfg: tmp_path)
    _patch_experiment_heavy_fns(monkeypatch, tmp_path, captured, _fake_result())

    result = runner.invoke(app, ["experiment", "--recipe", "steady", "--quick", "--out", str(tmp_path / "runs")])

    assert result.exit_code == 0, result.stdout
    uni = captured["run_experiment_recipe_universe"]
    assert uni == short_recipe.universe
    for sym in PIT_ADDITIONS:
        assert sym not in uni
    assert SURVIVORSHIP_MARKER in result.stdout
```

If the seeds test builds its `short_recipe`/`fake_result` inline rather than via helpers, factor those into module-level `_short_recipe()` / `_fake_result()` helpers (reused by both tests) as part of this step — do not duplicate the literals.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_experiment_command.py -k "pit_universe or default_universe" -v`
Expected: FAIL — unknown option `--pit-universe` (exit code 2).

- [ ] **Step 3: Add the flag, the swap, and the marker/caveat selection**

In `cli/experiment/command.py`:

(a) Imports (lines 15-16) become:

```python
from cli.experiment.caveats import EXPERIMENT_CAVEATS, PIT_MARKER, POINT_IN_TIME, SURVIVORSHIP_MARKER
from cli.experiment.recipes.base import resolve_recipe, with_pit_universe
```

(b) Add the option after the `deterministic` option (after line 65, before the closing `) -> None:`):

```python
    pit_universe: bool = typer.Option(
        False,
        "--pit-universe/--no-pit-universe",
        help="Expand the recipe's universe to point-in-time membership (adds the ever-top-25 "
        "delisted/faded majors) for a survivorship-free run. Default off.",
    ),
```

(c) Right after the `logger.info("recipe-resolved", …)` line (line 89), add:

```python
    if pit_universe:
        recipe = with_pit_universe(recipe)
    caveats = [POINT_IN_TIME] if pit_universe else EXPERIMENT_CAVEATS
    marker = PIT_MARKER if pit_universe else SURVIVORSHIP_MARKER
```

(d) `build_report` call (line 135): add `marker=marker`:

```python
    fig = build_report(result, cv=cv_arg, marker=marker)
```

(e) `run_meta` caveats (line 217): `"caveats": EXPERIMENT_CAVEATS,` → `"caveats": caveats,`

(f) stdout marker (line 261): `typer.echo(f"⚠ {SURVIVORSHIP_MARKER}")` → `typer.echo(f"⚠ {marker}")`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_experiment_command.py -v`
Expected: PASS (the 2 new tests + all existing command tests).

- [ ] **Step 5: Update README Usage**

In `README.md`, under the `zcrypto experiment` options in `## Usage`, add a row/line documenting `--pit-universe/--no-pit-universe` (default off): "Expand the recipe's universe to point-in-time membership (the ever-top-25 delisted/faded majors) for a survivorship-free run." Match the existing option-list formatting (do not hand-edit the mdformat-owned TOC).

- [ ] **Step 6: Lint + full experiment-suite check + commit**

```bash
uv run ruff check --fix cli/experiment/command.py tests/test_experiment_command.py
uv run ruff format cli/experiment/command.py tests/test_experiment_command.py
uv run pytest tests/test_experiment_command.py tests/test_experiment_recipe.py tests/test_experiment_caveats.py tests/test_experiment_report.py -q
git add cli/experiment/command.py tests/test_experiment_command.py README.md
git commit -m "feat(experiment): add --pit-universe flag for survivorship-free runs"
```

Expected: the targeted suite passes.

---

## Closeout (operational — run by the orchestrator after Tasks 1-3 land, NOT a subagent task)

These produce the real artifacts and the verdict; author the completed-work docs here (per `.claude/rules/iterations-history.md`), when the work is real.

1. **Acquire Terra LUNA into `./data`** (reusing existing commands; RECON the exact boundary):
   - RECON the Luna-2.0-launch boundary (the first `LUNAUSDT` date that is Luna 2.0, ~2022-05-28) and the real `LUNCUSDT` listing date.
   - `zcrypto data download` `LUNAUSDT` capped `--to <boundary>` (+ `--allow-interior-gaps` if the May-2022 crash has halt-day 404s) and `LUNCUSDT` (full); then `zcrypto data rename LUNAUSDT LUNCUSDT`; then `zcrypto data verify` → confirm `LUNCUSDT` spans the crash → today.
2. **Append `LUNCUSDT` to `PIT_ADDITIONS`** in `cli/experiment/recipes/base.py` (one-line edit), update `test_pit_additions_are_the_ten_delisted_faded_majors` to the 11-tuple, re-run `uv run pytest tests/test_experiment_recipe.py -k pit`; commit `feat(experiment): add Terra LUNCUSDT to the point-in-time universe`. Dispatch a review subagent (per `commit-messages.md`).
3. **Re-measure** all 5 recipes (`skeleton`, `steady`, `alpha360_steady`, `crossasset_steady`, `regime_steady`) survivor-vs-PIT at `--seeds 16` (e.g. `zcrypto experiment --recipe <r> --seeds 16` and `… --pit-universe --seeds 16`); redis must be up (`scripts/redis.sh start`). Record, per recipe, the survivor-vs-PIT holdout distribution (ending value, Sharpe, PSR) and the **survivorship inflation** (how far PIT sits below survivor, read against the seed-noise band).
4. **Resolve `T0005`** — flip front-matter `open`→`resolved` (follow the archive convention now that PR #50 is merged: `git mv docs/open-topics/T0005-point-in-time-universe.md docs/open-topics/archive/` and point the index link at `archive/`; move the README bullet to R&D `### Resolved`). Record the resolution (the verdict) in the topic + the commit.
5. **Open the parked follow-up open-topic** (force-liquidate-to-cash — the frozen delisting capital that the freeze does not redeploy) via the mandatory approval gate in `.claude/rules/open-topics.md`.
6. **Docs:** the per-recipe survivorship-inflation verdict into `docs/iterations-history.md` (iter-18 entry) + the recipe docstrings (superseding the survivor-only numbers); confirm the README `--pit-universe` line landed in Task 3.

---

## Self-Review

**Spec coverage:** Decision 1 (Terra) → Closeout 1-2; Decision 2 (PIT via flag) → Tasks 1+3; Decision 3 (freeze, no code) → Architecture note + Closeout (no task, correct); Decision 4 (re-measure all 5) → Closeout 3; Decision 5 (force-liquidate parked) → Closeout 5. The caveat/marker flip (spec §"the run's honesty marker must reflect reality", implicit) → Task 2. README (spec component tree) → Task 3 Step 5. All covered.

**Placeholder scan:** No TBD/TODO. The only deferred concretes are the Terra RECON dates (boundary + LUNC listing) — correctly a closeout RECON, not a coded step. Test helper names `_short_recipe()`/`_fake_result()` reference the existing seeds-test pattern, with an explicit instruction to factor them if inline.

**Type consistency:** `PIT_ADDITIONS: tuple[str, ...]` and `with_pit_universe(recipe) -> Recipe` named identically across Tasks 1+3; `POINT_IN_TIME`/`PIT_MARKER`/`marker=` named identically across Tasks 2+3; `build_report(..., marker=…)` signature matches its call site.
