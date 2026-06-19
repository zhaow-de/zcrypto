# Deterministic experiments + multi-seed holdout distribution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Report the holdout as a multi-seed distribution (`--seeds N`) so the iter-13 recipe comparison can be re-run and judged "is the cross-asset edge beyond the seed-noise band?", with opt-in bit-determinism (`--deterministic`, default off) — without slowing the default/dev/test path. Resolves `T0011`.

**Architecture:** A `seed` flows through `model_config.kwargs` into both fit sites (`scaffold`'s `LGBModel`, `cpcv._lgb_params`); `--deterministic` adds `deterministic=True`+`force_row_wise=True`. `--seeds N` fits the **holdout** N times (seeds `1…N`) via the existing light `lgb.train`+`backtest()` path (reused from `walkforward`/`cpcv`), aggregates per-seed metrics into a distribution written as `holdout_seeds.json`; CPCV runs once. A pure aggregation + separation read drives the verdict.

**Tech Stack:** Python 3.12, uv, qlib, LightGBM, pandas, pytest, ruff (line length 132). Redis for `experiment`.

## Global Constraints

- **Default path stays fast:** `--seeds 1` (default) + no `--deterministic` ⇒ today's behavior; tests, `--quick`, dev iteration pay nothing. `--deterministic` is the only thing that adds the ~2–4×/fit determinism cost, and only when passed.
- **Single-run path preserved:** `--seeds 1` produces the existing single-fit bundle (CPCV once + the MLflow holdout) — the multi-seed distribution is additive (`holdout_seeds.json`), not a replacement.
- **Light-path metric parity:** the per-seed holdout metrics (ending value, absolute Sharpe, PSR, max-drawdown) use the SAME definitions as the single-fit holdout (`scaffold._extract_metrics`, the holdout-PSR computation) so they're comparable.
- **Leak-free:** the per-seed holdout trains on the recipe's train segment and predicts the test segment, same purge discipline as the existing holdout (no new leakage surface).
- ruff clean; each commit gets a subagent `Reviewed-by:` before push.

## File structure

```
cli/experiment/
├── cpcv.py          # MODIFY: _lgb_params(recipe, *, seed=None, deterministic=False) injects seed / deterministic / force_row_wise
├── scaffold.py      # MODIFY: seed the holdout LGBModel build (model_config.kwargs) when seed/deterministic given; pass through run_experiment
├── walkforward.py   # MODIFY (small): pass seed/deterministic into _lgb_params (keeps wf reproducible-capable)
├── multiseed.py     # NEW: summarize_seed_metrics + separation (pure) ; run_holdout_seeds(recipe,*,data_dir,seeds,deterministic) (light per-seed holdout)
└── command.py       # MODIFY: --seeds / --deterministic options; thread through; write holdout_seeds.json when seeds>1
tests/
├── test_experiment_cpcv.py      # EXTEND: _lgb_params injects seed/deterministic when asked; omits by default
├── test_multiseed.py            # NEW: summarize_seed_metrics + separation (pure)
├── test_experiment_command.py   # EXTEND: --seeds/--deterministic option wiring (CliRunner + monkeypatch)
└── test_experiment_scaffold.py  # EXTEND (redis-gated): --seeds N -> holdout_seeds.json with N rows + aggregate; --deterministic reproduces; default unchanged
```

Tasks 1–4 build the capability; Task 5 is redis integration; Task 6 the re-run + closeout.

---

## Task 1: Seed / determinism plumbing in the fit params

**Files:** Modify `cli/experiment/cpcv.py` (`_lgb_params`), `cli/experiment/scaffold.py` (holdout model build), `cli/experiment/walkforward.py` (pass-through); Test `tests/test_experiment_cpcv.py`.

**Interfaces:**
- Produces: `cpcv._lgb_params(recipe, *, seed=None, deterministic=False) -> (params, num_boost_round)` — adds `seed` to params when not None; adds `deterministic=True` + `force_row_wise=True` when `deterministic`. `scaffold._seeded_model_config(model_config, *, seed=None, deterministic=False) -> dict` — returns a model_config with the same keys injected into `kwargs`.

- [ ] **Step 1: Failing tests** in `tests/test_experiment_cpcv.py`:
```python
def test_lgb_params_default_has_no_seed_or_determinism():
    from cli.experiment.cpcv import _lgb_params
    from cli.experiment.recipes.base import resolve_recipe
    params, _ = _lgb_params(resolve_recipe("steady"))
    assert "seed" not in params and "deterministic" not in params and "force_row_wise" not in params

def test_lgb_params_injects_seed_and_determinism():
    from cli.experiment.cpcv import _lgb_params
    from cli.experiment.recipes.base import resolve_recipe
    params, _ = _lgb_params(resolve_recipe("steady"), seed=7, deterministic=True)
    assert params["seed"] == 7
    assert params["deterministic"] is True and params["force_row_wise"] is True

def test_lgb_params_seed_without_determinism():
    from cli.experiment.cpcv import _lgb_params
    from cli.experiment.recipes.base import resolve_recipe
    params, _ = _lgb_params(resolve_recipe("steady"), seed=3)
    assert params["seed"] == 3 and "deterministic" not in params
```
And for the scaffold helper:
```python
def test_seeded_model_config_injects_into_kwargs():
    from cli.experiment.scaffold import _seeded_model_config
    mc = {"class": "LGBModel", "module_path": "m", "kwargs": {"learning_rate": 0.03}}
    out = _seeded_model_config(mc, seed=5, deterministic=True)
    assert out["kwargs"]["seed"] == 5 and out["kwargs"]["deterministic"] is True and out["kwargs"]["force_row_wise"] is True
    assert mc["kwargs"] == {"learning_rate": 0.03}  # input not mutated
    assert _seeded_model_config(mc)["kwargs"] == {"learning_rate": 0.03}  # no-op default
```

- [ ] **Step 2: Run — expect FAIL** (`uv run pytest tests/test_experiment_cpcv.py -q`).

- [ ] **Step 3: Implement.** In `cpcv._lgb_params`, add keyword-only `seed=None, deterministic=False`; after building `params`, set `params["seed"] = seed` when `seed is not None`, and `params.update({"deterministic": True, "force_row_wise": True})` when `deterministic`. In `scaffold.py` add `_seeded_model_config(model_config, *, seed=None, deterministic=False)` (non-mutating: deep-copy kwargs, inject). **RECON:** confirm against LightGBM that `deterministic=True` requires `force_row_wise` (or `force_col_wise`) and is reproducible multi-threaded (no `num_threads=1` needed); if LightGBM wants a different key, adjust + report.

- [ ] **Step 4: Thread through (no behavior change at defaults).** `run_experiment` (scaffold) gains `seed=None, deterministic=False` kwargs and builds the holdout model from `_seeded_model_config(recipe.model_config, seed=seed, deterministic=deterministic)`. `run_cpcv` (cpcv) and `run_walkforward_holdout` (walkforward) gain the same kwargs and pass them to `_lgb_params(recipe, seed=seed, deterministic=deterministic)`. Defaults (None/False) reproduce today's params exactly.

- [ ] **Step 5: Run — expect PASS + ruff.**

- [ ] **Step 6: Commit** — `feat(experiment): thread seed + deterministic into the LightGBM fit params` (+ `Co-Authored-By: Claude Opus 4.8` trailer).

---

## Task 2: Pure multi-seed aggregation + separation read

**Files:** Create `cli/experiment/multiseed.py` (pure functions only this task); Test `tests/test_multiseed.py`.

**Interfaces:**
- Produces: `summarize_seed_metrics(per_seed: list[dict]) -> dict` — given per-seed metric dicts (keys: `ending_value`, `sharpe`, `psr`, `max_drawdown`), returns `{metric: {"mean":…, "std":…, "min":…, "max":…, "n":…}}`. `separation(a: dict, b: dict, metric="sharpe") -> dict` — given two summaries, returns `{"mean_gap":…, "pooled_std":…, "z":mean_gap/pooled_std}` ("edge beyond the seed band?" read).

- [ ] **Step 1: Failing tests** `tests/test_multiseed.py`:
```python
from cli.experiment.multiseed import summarize_seed_metrics, separation

def _per_seed(vals):  # vals: list of sharpe values; fill others trivially
    return [{"ending_value": 10000*(1+v), "sharpe": v, "psr": 0.5, "max_drawdown": -0.5} for v in vals]

def test_summarize_basic_stats():
    s = summarize_seed_metrics(_per_seed([0.0, 0.2, 0.4]))
    assert s["sharpe"]["n"] == 3
    assert abs(s["sharpe"]["mean"] - 0.2) < 1e-9
    assert s["sharpe"]["min"] == 0.0 and s["sharpe"]["max"] == 0.4
    assert s["sharpe"]["std"] > 0

def test_separation_z():
    a = summarize_seed_metrics(_per_seed([0.5, 0.5, 0.5]))  # crossasset-like, tight
    b = summarize_seed_metrics(_per_seed([0.0, 0.0, 0.0]))  # steady-like, tight
    sep = separation(a, b, metric="sharpe")
    assert abs(sep["mean_gap"] - 0.5) < 1e-9
    assert sep["z"] > 0  # a separated above b
def test_separation_within_noise():
    a = summarize_seed_metrics(_per_seed([0.0, 0.3, -0.3, 0.4, -0.4]))
    b = summarize_seed_metrics(_per_seed([0.05, 0.25, -0.25, 0.35, -0.35]))
    sep = separation(a, b, metric="sharpe")
    assert abs(sep["z"]) < 1.0  # overlapping distributions -> not separated
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** the two pure functions (numpy/statistics; population or sample std — use sample std `ddof=1` for n>1, 0 for n=1; `pooled_std = sqrt((std_a^2 + std_b^2)/2)`, guard divide-by-zero → `z=inf` sentinel or `None`). No qlib import.
- [ ] **Step 4: Run — expect PASS + ruff.**
- [ ] **Step 5: Commit** — `feat(experiment): add pure multi-seed metric aggregation + separation read`.

---

## Task 3: Per-seed light holdout runner

**Files:** Modify `cli/experiment/multiseed.py` (add `run_holdout_seeds`); Test `tests/test_multiseed.py` (a thin unit) + exercised redis-gated in Task 5.

**Interfaces:**
- Consumes: `summarize_seed_metrics` (Task 2); the light holdout machinery in `walkforward`/`cpcv` (`_lgb_params`, `_materialize_span`, `_split_xy`, `_rows_on`, the qlib `backtest()` call, `exchange_kwargs`, `strategy_config_with_signal`); `scaffold._extract_metrics` + the holdout-PSR helper.
- Produces: `run_holdout_seeds(recipe, *, data_dir, seeds, deterministic=False) -> dict` — `{"per_seed": [ {seed, ending_value, sharpe, psr, max_drawdown}, … ], "summary": summarize_seed_metrics(...)}`.

**Design / RECON:** factor the single-fit light holdout out of `walkforward.run_walkforward_holdout` (the train [train_start..train_end] → predict [test_start..test_end] → `backtest()` → `report_df` block; one period spanning the test segment) into a reusable `_light_holdout(recipe, *, seed, deterministic) -> report_df` (or call it with the existing wf machinery). For each seed `1…N`: build the report_df, then derive metrics with the SAME helpers the single-fit holdout uses — ending value (cumulative of `return - cost`), absolute Sharpe (`risk_analysis` IR on `return-cost`, matching `_extract_metrics`), max-drawdown (from `_extract_metrics`), PSR (the existing holdout-PSR computation — RECON: locate it; iter-11 put the holdout PSR in `cv_results.json`/`stats.psr` over the holdout daily returns). **RECON the metric parity:** the base-seed light metric should ≈ the MLflow single-fit holdout metric for the same recipe (sanity-check one recipe). qlib must be initialized once (the wf path's `qlib.init` + cwd-isolation pattern) and reused across the N seeds.

- [ ] **Step 1: Failing test** — a thin unit that monkeypatches `_light_holdout` (the per-seed report_df producer) to return synthetic report_dfs for N seeds and asserts `run_holdout_seeds` returns `per_seed` of length N + a `summary` with the expected mean (tests the loop + aggregation wiring without qlib/redis). The real qlib run is Task 5.
```python
def test_run_holdout_seeds_aggregates(monkeypatch):
    from cli.experiment import multiseed as ms
    # stub the per-seed metric producer so no qlib/redis is needed
    monkeypatch.setattr(ms, "_holdout_metrics_for_seed",
                        lambda recipe, seed, deterministic, ctx: {"ending_value": 10000+seed, "sharpe": 0.1*seed, "psr": 0.3, "max_drawdown": -0.4})
    monkeypatch.setattr(ms, "_holdout_context", lambda recipe, data_dir, deterministic: object())
    out = ms.run_holdout_seeds(_fake_recipe(), data_dir="x", seeds=4)
    assert len(out["per_seed"]) == 4
    assert out["summary"]["sharpe"]["n"] == 4
```
(Structure `run_holdout_seeds` with a thin `_holdout_metrics_for_seed(recipe, seed, deterministic, ctx)` seam + a `_holdout_context(...)` that does the one-time qlib.init/materialize, so the loop+aggregation are unit-testable and the heavy qlib work is isolated + monkeypatchable.)

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** `run_holdout_seeds` + the `_holdout_context`/`_holdout_metrics_for_seed` seams + `_light_holdout` (reusing the wf block). Vary `seed=k` per iteration via `_lgb_params(recipe, seed=k, deterministic=deterministic)`.
- [ ] **Step 4: Run — expect PASS + ruff** (the unit; the redis path is Task 5).
- [ ] **Step 5: Commit** — `feat(experiment): add multi-seed light-holdout runner (run_holdout_seeds)`.

---

## Task 4: CLI `--seeds` / `--deterministic` + write `holdout_seeds.json`

**Files:** Modify `cli/experiment/command.py`; Test `tests/test_experiment_command.py`.

**Interfaces:** Consumes Task 1 (seed/deterministic kwargs on `run_experiment`/`run_cpcv`) + Task 3 (`run_holdout_seeds`).

- [ ] **Step 1: Failing test** (CliRunner + monkeypatch the heavy fns, like the existing command tests):
```python
def test_experiment_passes_seeds_and_deterministic(monkeypatch, tmp_path):
    # monkeypatch run_cpcv / run_experiment / run_holdout_seeds to capture kwargs; assert:
    #  --seeds 5 --deterministic -> run_holdout_seeds called with seeds=5, deterministic=True
    #  default -> run_holdout_seeds NOT called (or seeds=1 fast path); run_experiment gets deterministic=False
    ...
```
(Follow the file's existing monkeypatch pattern; assert the wiring, not a real run.)

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement.** Add `seeds: int = typer.Option(1, "--seeds", help="...")` and `deterministic: bool = typer.Option(False, "--deterministic/--no-deterministic", help="...")`. Thread `deterministic` into `run_cpcv` + `run_experiment`. When `seeds > 1`, call `run_holdout_seeds(recipe, data_dir=..., seeds=seeds, deterministic=deterministic)` and write `bundle/holdout_seeds.json` (`per_seed` + `summary`). The canonical single-fit bundle (positions/report) is still produced by `run_experiment` at the base seed. Log a `holdout-seeds` event (n_seeds, summary).
- [ ] **Step 4: Run — expect PASS + ruff + README.** Update README `## Usage` for `--seeds`/`--deterministic` + `holdout_seeds.json` (mdformat owns the TOC).
- [ ] **Step 5: Commit** — `feat(experiment): add --seeds / --deterministic to the experiment command`.

---

## Task 5: Integration (redis-gated)

**Files:** Test `tests/test_experiment_scaffold.py` (extend).

**RECON:** reuse the existing `_redis_up()`/skip marker + synthetic fixture + `_FIXTURE_SEGMENTS`.

- [ ] **Step 1: Test(s)** (redis-gated), keeping the fixture run small (e.g. `--seeds 3`):
  1. `experiment --seeds 3` on the fixture writes `holdout_seeds.json` with 3 `per_seed` rows + a `summary` (mean/std/min/max), and the run completes.
  2. default (`--seeds 1`, no `--deterministic`) still writes the existing bundle and **no** `holdout_seeds.json` regression (or seeds=1 writes a 1-row file — pick per Task 4's design and assert it).
  3. **determinism reproduces:** two `--deterministic --seeds 1` runs of the same recipe produce identical holdout metrics (the bit-repro guarantee); without `--deterministic`, the per-seed values differ across seeds (variance is real).
- [ ] **Step 2: Run** (Redis up): `scripts/redis.sh start`; `uv run pytest tests/test_experiment_scaffold.py -q`. Watch output is pristine.
- [ ] **Step 3: Commit** — `test(experiment): redis-gated integration — multi-seed holdout distribution + determinism reproducibility`.

---

## Task 6: Re-run + closeout

**Files:** Modify `docs/open-topics/T0011-*.md` + `docs/open-topics/README.md`; the iter-13 recipe docstrings (`steady.py`, `alpha360_steady.py`, `crossasset_steady.py`, `skeleton.py` as relevant); `docs/iterations-history.md`; README if not done in Task 4.

- [ ] **Step 1: Re-run.** Redis up; for each of `skeleton`, `steady`, `alpha360_steady`, `crossasset_steady`, run `zcrypto experiment --recipe <r> --seeds 16 --out /tmp/zcrypto_iter14` (fast, no `--deterministic`). Collect each `holdout_seeds.json` summary; compute the `separation` of `crossasset_steady` vs `steady` (and vs `skeleton`) on Sharpe.
- [ ] **Step 2: Verdict.** Record honestly: each recipe's holdout distribution (mean±std of ending value / Sharpe / PSR / max-DD over 16 seeds); whether `crossasset_steady`'s Sharpe mean is separated from `steady`'s beyond the pooled std (edge real vs seed-noise); whether `alpha360_steady` stays worst. Write the multi-seed verdict into the recipe docstrings (superseding the iter-13 single-run notes) and the iter-14 iterations-history entry.
- [ ] **Step 3: Resolve `T0011`.** Flip front-matter `status: open → resolved`; add a `## Resolution` note (determinism flag + multi-seed distribution shipped; single-run verdicts retired; the re-run's finding). Move its bullet `## Open → ## Resolved` in `docs/open-topics/README.md`. (Note multi-seed-CPCV as a residual in the resolution if still relevant.)
- [ ] **Step 4: iterations-history.** Append the iter-14 entry: the seed/determinism plumbing, `--seeds`/`--deterministic`, the multi-seed holdout distribution + `holdout_seeds.json` + the separation read, the re-run verdict, `T0011` resolved, `T0012` deferred.
- [ ] **Step 5: Commit** — `docs(experiment): iter-14 closeout — multi-seed verdict, T0011 resolved, iterations-history`.

---

## Self-review

- **Spec coverage:** `--seeds` multi-seed holdout distribution (Tasks 3–4) ✓; `--deterministic` opt-in, default off (Tasks 1, 4) ✓; per-seed via the light reuse path (Task 3) ✓; `holdout_seeds.json` artifact (Task 4) ✓; separation read (Task 2) ✓; default/test path unchanged (Global Constraints + Task 5) ✓; re-run + verdict + `T0011` resolved + `T0012` deferred (Task 6) ✓.
- **Type consistency:** `_lgb_params(recipe, *, seed, deterministic)`, `_seeded_model_config(model_config, *, seed, deterministic)`, `summarize_seed_metrics(list[dict])->dict`, `separation(a,b,metric)->dict`, `run_holdout_seeds(recipe,*,data_dir,seeds,deterministic)->{per_seed,summary}` — consistent across tasks.
- **Risk flags:** Task 1 (exact LightGBM determinism keys) and Task 3 (factoring the light holdout out of `walkforward`; metric parity with the MLflow holdout; one-time qlib.init reuse) carry RECON notes; the pure logic (Tasks 1 params, 2 aggregation) is isolated + unit-tested, so the integration surface is small.
