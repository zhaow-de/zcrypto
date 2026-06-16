# `zcrypto experiment --recipe skeleton` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `zcrypto experiment --recipe <name>` command that runs an end-to-end Qlib train → backtest → report cycle on the `./data` provider, with a single swappable recipe module, a fingerprint-busted disk cache, and a predict-ready run bundle, headlining the ending USDT value over the test window.

**Architecture:** Reuse the proven `cli/example/workflow.py` pipeline shape (qlib.init → DatasetH → model.fit → R.start + SignalRecord + PortAnaRecord → recorder.load_object). A frozen `Recipe` dataclass (the moving part, selected by `--recipe` → `cli/experiment/recipes/<name>.py`) supplies the handler/model/strategy/segments/universe/costs. Fixed scaffolding adds disk-cache fingerprint busting, persistence of the MLflow store + a per-run bundle, and a 3-panel Plotly report.

**Tech Stack:** Python 3.12, pyqlib 0.9.7, lightgbm 4.6.0 (already in `uv.lock`), plotly + kaleido (to add), Typer, pytest, uv. Spec: `docs/specs/00006-experiment-skeleton-design.md`. **Depends on plan `00005`** (provider at `./data`, cache at `./data/cache`).

---

## Prerequisite & conventions

**Prerequisite:** plan `00005` must be merged to `develop` before this plan starts — it provides the `./data` provider, the `./data/cache` location, and the refactored `verify_dataset(data_dir)` signature this plan's fixture test reuses. Both plans also touch `README.md`, `docs/iterations-history.md`, `pyproject.toml`, and `cli/__main__.py`; run `00006` **after** `00005` merges (or rebase atop it) to avoid conflicts on those files. Do **not** run the two in parallel.

**Commit & review conventions (every task below):** implementation commits are **not** review-exempt. Each ends with a blank line + `Co-Authored-By: <actual model> <noreply@anthropic.com>`, and is reviewed by a separate subagent before push (amend a `Reviewed-by: <reviewer model> <noreply@anthropic.com>` trailer while the commit is still local). The per-step `git commit  # "<subject>"` lines show the subject only.

## Reference: confirmed qlib API (from `cli/example/workflow.py`)

- `qlib.init(provider_uri=..., region=REG_US, exp_manager={"class":"MLflowExpManager","module_path":"qlib.workflow.expm","kwargs":{"uri":exp_uri,"default_exp_name":...}}, logging_config=None)`.
- Dataset via `init_instance_by_config({"class":"DatasetH","module_path":"qlib.data.dataset","kwargs":{"handler":{...},"segments":{"train":...,"valid":...,"test":...}}})`.
- Backtest sequence inside `with R.start(experiment_name=...)`: `model.fit(dataset)`; `recorder = R.get_recorder()`; `SignalRecord(model, dataset, recorder).generate()`; `PortAnaRecord(recorder, port_cfg, "day").generate()`.
- Recorder artifacts: `recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")` (DataFrame indexed by (category, metric)); `recorder.load_object("portfolio_analysis/report_normal_1day.pkl")` (dict with `"return"`, `"cost"`). Positions: `"portfolio_analysis/positions_normal_1day.pkl"`.
- `exchange_kwargs` keys: `freq`, `deal_price`, `open_cost`, `close_cost`, `min_cost`.
- MLflow-cwd workaround: run inside `tempfile.TemporaryDirectory` + `contextlib.chdir` + `subprocess.run(["git","init","-q"])` before `qlib.init`; this also restores cwd and prevents `private/` scaffolding leaking. The example test asserts cwd restored, no `private/` leak, and no "Fail to log the uncommitted code" log records.
- Metrics via `qlib.contrib.evaluate.risk_analysis(report["return"] - report["cost"], freq="day")`; finite-metric assertions use `math.isfinite`.

## File Structure

- `cli/experiment/__init__.py`, `command.py`, `scaffold.py`, `report.py`, `cache.py`, `stress.py`
- `cli/experiment/recipes/__init__.py`, `base.py`, `skeleton.py`
- `cli/experiment/data/` — committed synthetic qlib fixture (+ a `scripts/gen_fixture.py` generator, excluded from the wheel like `cli/example/scripts`)
- `tests/test_experiment_*.py`
- `cli/__main__.py` (wire the command), `pyproject.toml` (deps + wheel excludes + coverage omit), `README.md`, `docs/iterations-history.md`, `runs/.gitignore`

---

### Task 1: Dependencies + qlib API reconnaissance (resolve the unknowns)

**Files:** `pyproject.toml`; throwaway spike (not committed).

- [ ] **Step 1: Add deps** — `lightgbm 4.6.0` is already present transitively (confirmed in `uv.lock`); add only the two missing ones: `uv add plotly kaleido`. Confirm `uv run python -c "import lightgbm, plotly, kaleido; print(lightgbm.__version__)"` succeeds. Do **not** commit `pyproject.toml`/`uv.lock` until every Step-2 spike below has passed (Step 4).
- [ ] **Step 2: Confirm the qlib symbols** by spiking in a scratch REPL/script (delete after):
  - `from qlib.contrib.data.handler import Alpha158` — confirm import path + that its kwargs accept `instruments`, `start_time`, `end_time`, `fit_start_time`, `fit_end_time`, `infer_processors`, `learn_processors`, `freq`, `label`.
  - `from qlib.contrib.model.gbdt import LGBModel` — confirm path + accepted kwargs (e.g. `loss`, `num_leaves`, `learning_rate`, `num_boost_round`, `early_stopping_rounds`/`early_stopping`).
  - `qlib.init(..., expression_cache=..., dataset_cache=...)` — confirm the **exact** kwarg names and the accepted values (class name string `"DiskExpressionCache"`/`"DiskDatasetCache"` vs dotted module path). Record what makes qlib write a `cache/` dir under `provider_uri`.
  - The fractional-trading knob: confirm whether `exchange_kwargs` accepts `trade_unit=None` (or `min_cost`/`trade_unit`/`volume_threshold` semantics) so a 10k account can hold fractional BTC/ETH. Record the exact key.
  - The positions artifact: run `uv run zcrypto example` (or a quick fixture backtest), open the recorder's `portfolio_analysis/positions_normal_1day.pkl`, and record its structure (type, index, per-day shape) so Task 6's trade-delta extraction is built against the real shape, not a guess.
- [ ] **Step 3: Record findings** inline in `scaffold.py` as comments and in this plan's task notes; the later tasks depend on them. If any symbol differs from the assumptions above, adjust the relevant task before implementing it.
- [ ] **Step 4: Commit** the dependency bump:

```bash
git add pyproject.toml uv.lock
git commit  # "build(experiment): add plotly + kaleido deps"
```

---

### Task 2: Synthetic qlib fixture

**Files:** Create `cli/experiment/data/scripts/gen_fixture.py`; generate `cli/experiment/data/<provider>/` (committed). Test: `tests/test_experiment_fixture.py`.

The fixture is a tiny qlib file-format dataset reusing the writer in `cli/data/qlib_writer.py` (`write_calendar`, `write_instruments`, `write_bin`) so it matches the real layout.

- [ ] **Step 1:** Write `gen_fixture.py` to synthesize a **small** dataset sized for fast tests — NOT the real 2020–2026 span. The fixture exists only to exercise the pipeline end-to-end quickly, so it pairs with a **fixture-scoped recipe variant** carrying short truncated segments (e.g. train 8 months / valid 1 month / test 2 months). Size the calendar to cover Alpha158's longest window (~60 bars) plus those segments — roughly **18 months (~540 daily bars)** spanning a fake stress window so the shading path is exercised. Include **all 21 symbols**: the 19 USDT-quoted pairs the real skeleton trades (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, AVAXUSDT, LINKUSDT, DOGEUSDT, TRXUSDT, DOTUSDT, POLUSDT, LTCUSDT, ATOMUSDT, UNIUSDT, NEARUSDT, ARBUSDT, APTUSDT, PEPEUSDT) **plus** the 2 reference instruments `BTCEUR` + `ETHBTC`. Use deterministic seeded walks (no runtime `random`). Write the **exact `FIELDS` set from `cli/data/config.py`** (`open, high, low, close, volume, amount, trades, taker_buy_base, taker_buy_amount, vwap, factor` — Alpha158 needs `$close`/`$volume`/`$vwap`, and `$factor` for adjusted prices) via `cli/data/qlib_writer` (`write_calendar`, `write_instruments`, `write_bin`), plus an `index.json` via the `cli/data/index` writers so cache fingerprinting has a hashable `index.json`. The real skeleton recipe keeps its 2020–2026 segments for the live `./data`; the integration test (Task 5) uses the fixture recipe variant.
- [ ] **Step 2:** Run it; commit the generated provider dir + the script.
- [ ] **Step 3: Test** `tests/test_experiment_fixture.py`: assert the fixture loads — `verify_dataset(<fixture>).ok` (reuse the data verifier) and that `BTCUSDT/BTCEUR/ETHBTC` dirs exist with the expected bar count.
- [ ] **Step 4:** Add `cli/experiment/data/scripts/**` to the wheel `exclude` and coverage `omit` in `pyproject.toml` (mirror the `cli/example/scripts` entries).
- [ ] **Step 5: Commit** — `feat(experiment): add synthetic qlib test fixture + generator`.

---

### Task 3: `Recipe` contract + `skeleton` recipe + resolver

**Files:** Create `cli/experiment/recipes/base.py`, `skeleton.py`, `__init__.py`. Test: `tests/test_experiment_recipe.py`.

- [ ] **Step 1: Test** — `resolve_recipe("skeleton")` returns a `Recipe` with `name=="skeleton"`, the 19-pair `universe`, `reference_instruments == ["BTCEUR","ETHBTC"]`, `account == 10_000`, `benchmark == "BTCUSDT"`, `fee_preset == "vip2_bnb"`, and `segments` with the three windows; `resolve_recipe("nope")` raises a clear error listing available recipe files.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** `base.py` (the `Recipe` frozen dataclass per the spec), a `FEE_PRESETS = {"vip2_bnb": (0.0006, 0.0006), "vip2_std": (0.0008, 0.0008), "zero": (0.0, 0.0)}` map, and `resolve_recipe(name)` using `importlib.import_module(f"cli.experiment.recipes.{name}")` returning its module-level `RECIPE` (catch `ModuleNotFoundError` → list `recipes/*.py`). Implement `skeleton.py` building the Alpha158 handler config, the `LGBModel` model config, the `TopkDropoutStrategy(topk=5,n_drop=1)` strategy config, the label `["Ref($close,-2)/Ref($close,-1)-1"]`/`["LABEL0"]`, the 19-pair `universe` (ADA/APT/ARB/ATOM/AVAX/BNB/BTC/DOGE/DOT/ETH/LINK/LTC/NEAR/PEPE/POL/SOL/TRX/UNI/XRP + `USDT`), and `segments` train `("2020-01-01","2023-12-31")` / valid `("2024-01-01","2024-12-31")` / test `("2025-01-01","2026-06-15")`.
- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(experiment): add Recipe contract + skeleton recipe + resolver`.

---

### Task 4: Disk-cache fingerprint busting

**Files:** Create `cli/experiment/cache.py`. Test: `tests/test_experiment_cache.py`.

- [ ] **Step 1: Test** — given a temp `data_dir` containing an `index.json` and a `cache/` dir with a stale `.dataset_fingerprint`: `ensure_cache_fresh(data_dir, refresh=False)` wipes `cache/` and writes the current `sha256(index.json)`; a second call is a no-op (fingerprint matches); `refresh=True` always wipes. Missing `cache/` is fine (no error).
- [ ] **Step 2: Run → fail. Step 3: Implement** `ensure_cache_fresh(data_dir: Path, *, refresh: bool=False) -> None`: compute `sha256` of `data_dir/"index.json"`; compare to `data_dir/"cache"/".dataset_fingerprint"`; if differ or `refresh`, `shutil.rmtree(data_dir/"cache", ignore_errors=True)`. Provide `record_fingerprint(data_dir)` to call **after** qlib has populated the cache. (Reuse `cli.data.index.compute_sha256`.)
- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(experiment): add index.json-fingerprint cache busting`.

---

### Task 5: Scaffolding (the train → backtest → extract pipeline)

**Files:** Create `cli/experiment/scaffold.py`, `cli/experiment/stress.py`. Test: `tests/test_experiment_scaffold.py` (integration, against the Task-2 fixture).

- [ ] **Step 1:** `stress.py` — `STRESS_WINDOWS = [("LUNA","2022-05-07","2022-05-16"), ("FTX","2022-11-06","2022-11-14")]`.
- [ ] **Step 2: Integration test** — `run_experiment(recipe, data_dir=<fixture>, out_dir=<tmp>, refresh_cache=True)` returns a result whose `metrics` are all `math.isfinite`, `ending_value > 0`, `account_curve` is a non-empty series starting at `recipe.account`, and `trades` is a DataFrame. Assert `<out_dir>/mlruns` was written and `cache/` + `.dataset_fingerprint` exist under the fixture dir. (Use a fixture-scoped recipe variant with a short fit window if Alpha158-over-full-history is slow; keep segments inside the fixture's calendar.)
- [ ] **Step 3: Run → fail. Step 4: Implement** `scaffold.py`, adapting `example/workflow.py`:
  - `ensure_cache_fresh(data_dir, refresh=refresh_cache)` before init.
  - The temp-cwd + `git init` MLflow workaround, but with `exp_uri` pointed at a **persistent** `out_dir/"mlruns"` (resolve to absolute `file://` URI; keep the cwd trick to avoid the relative-mkdir bug — confirmed in Task 1).
  - `qlib.init(provider_uri=str(data_dir), region=REG_US, expression_cache=<confirmed>, dataset_cache=<confirmed>, exp_manager=..., logging_config=None)`.
  - Build dataset from `recipe.handler_config`/`segments`/`universe`; `init_instance_by_config(recipe.model_config)`; `model.fit`.
  - `with R.start(experiment_name=recipe.name)`: `R.save_objects(trained_model=model)`; `SignalRecord(...).generate()`; `PortAnaRecord(recorder, _port_cfg(recipe, model, dataset), "day").generate()`.
  - `_port_cfg` builds `exchange_kwargs` from the fee preset (`open_cost`/`close_cost` from `FEE_PRESETS`, `min_cost=0`, `deal_price="close"`, `freq="day"`, fractional `trade_unit=<confirmed>`), `account=recipe.account`, `benchmark=recipe.benchmark`, `end_time = test_end - 1 day` (the example's look-ahead guard).
  - Extract: account-value series + return/cost/turnover from `report_normal_1day.pkl`; positions from `positions_normal_1day.pkl`; excess metrics from `port_analysis_1day.pkl`; absolute metrics from `risk_analysis`. `record_fingerprint(data_dir)`. Return a `RunResult` dataclass (metrics, account_curve, benchmark_curve inputs, trades, run_id).
  - JSONL log events at: cache check/bust, init, dataset build, fit start/finish, backtest, metrics, done. Use `cli.logging.get_logger("experiment.scaffold")`.
- [ ] **Step 5: Run → pass. Step 6: Commit** — `feat(experiment): scaffold train→backtest→extract pipeline`.

---

### Task 6: Trades extraction (text + data)

**Files:** Add to `cli/experiment/scaffold.py` (or `trades.py`). Test: `tests/test_experiment_trades.py`.

- [ ] **Step 1: Test** — `trades_from_positions(positions)` turns a positions-over-time structure into a DataFrame `[date, side, symbol, qty, price, value]` where buys are positive qty deltas and sells negative, priced at close; a `trade_summary(trades)` returns counts (total/buys/sells), turnover, and per-symbol counts. Use a small hand-built positions fixture.
- [ ] **Step 2: Run → fail. Step 3: Implement** the day-over-day position-delta diff. **Verify the `positions_normal_1day.pkl` structure** during implementation (it may be a dict of qlib `Position` objects keyed by date) and adapt the accessor accordingly.
- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(experiment): derive buy/sell trades from positions`.

---

### Task 7: Plotly 3-panel report

**Files:** Create `cli/experiment/report.py`. Test: `tests/test_experiment_report.py`.

- [ ] **Step 1: Test** — `build_report(result, recipe, reference_series, stress_windows)` returns a Plotly `Figure` with 3 subplot rows; `write_report(fig, out_dir, svg=False)` writes `report.html` (contains the inline plotly.js and the strategy + benchmark traces); with `svg=True` also writes `report.svg`. Assert the html file exists and is non-trivial; assert the figure has the expected number of traces and that LUNA/FTX shapes are present on panel 3.
- [ ] **Step 2: Run → fail. Step 3: Implement** the 3-panel figure (equity rebased to `account` at test start; trade timeline date×symbol; full-history context with `BTCUSDT/BTCEUR/ETHBTC` rebased + LUNA/FTX `vrect`s). `write_html(fig, include_plotlyjs="inline")`; `--svg` via `fig.write_image(..., format="svg")`. Reference-line prices are fetched in `scaffold.py` via `D.features(reference_instruments, ["$close"], ...)` and passed in.
- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(experiment): 3-panel Plotly report (equity / trades / LUNA-FTX context)`.

---

### Task 8: CLI command + run-bundle write + wiring

**Files:** Create `cli/experiment/command.py`; modify `cli/__main__.py`. Test: `tests/test_experiment_command.py`.

- [ ] **Step 1: Test** (CliRunner, against the fixture via `--data-dir`) — `experiment --recipe skeleton --data-dir <fixture> --out <tmp> --no-open` exits 0, prints the `10,000 → … USDT` headline + trade summary, and writes `<tmp>/<recipe>/<ts>/{report.html,metrics.json,trades.csv,run_meta.json,recipe_snapshot.json,model.pkl}`; `--recipe nope` exits non-zero with the available-recipes message; `--refresh-cache` is accepted.
- [ ] **Step 2: Run → fail. Step 3: Implement** `command.py`: flags `--recipe` (default `skeleton`), `--data-dir` (default `./data`), `--out` (default `./runs`), `--open/--no-open` (auto-off when `not sys.stdout.isatty()`), `--svg/--no-svg`, `--refresh-cache`. Resolve the recipe, call `run_experiment`, build the bundle dir `out/<recipe>/<UTC-ts>/` (timestamp from `datetime.now(timezone.utc)`), write `metrics.json` / `trades.csv` / `run_meta.json` (per spec's manifest fields, incl. `index_fingerprint`, `git_commit`, `qlib`/`lightgbm` versions, `feature_names`) / `recipe_snapshot.json` / copy `model.pkl` from the recorder; build + write the report; echo the headline. Wire `app.command("experiment")(experiment)` in `cli/__main__.py` (deferred import of the heavy modules, mirroring `example`). Defer `import qlib` so `--version`/`--help` stay fast.
- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(experiment): add `experiment` command + predict-ready run bundle`.

---

### Task 9: gitignore, README, iterations-history closeout

**Files:** Create `runs/.gitignore`; modify `README.md`, `docs/iterations-history.md`.

- [ ] **Step 1:** Create `runs/.gitignore` (`*` + `!.gitignore`).
- [ ] **Step 2:** Add a `## Usage` `zcrypto experiment` section to `README.md` (the command, all flags, the 3-panel report, the run bundle, `mlflow ui` tip, the realistic-expectations caveat). Let mdformat own the TOC.
- [ ] **Step 3:** Run the full gate: `uv run ruff check && uv run ruff format --check && uv run pytest -q`. Expected: green.
- [ ] **Step 4:** Append a `## <YYYY-MM-DD> — iter-7: experiment skeleton` iterations-history entry (command, recipe-as-moving-part, Alpha158+LGBM+TopkDropout, fee presets, fractional trading, cache fingerprint busting, 3-panel report, run bundle, deferred items → open-topics).
- [ ] **Step 5: Commit** — `docs(experiment): README usage + iter-7 iterations-history` + `runs/.gitignore`.
- [ ] **Step 6:** Open the PR into `develop` (`feat(experiment): iter-7 — end-to-end Qlib experiment harness`). *(finishing-a-development-branch step.)*

---

## Self-review notes

- **Unknowns are resolved in Task 1 before being relied on** (Alpha158 path, `LGBModel` path, cache kwargs, `trade_unit`, persistent mlruns) — not guessed. Later tasks say "use the confirmed symbol".
- **Spec coverage:** recipe/resolver (T3), result shape + fees + fractional (T5), cache + fingerprint (T4), trades text+plot (T6,T7), 3-panel report + LUNA/FTX (T7), run bundle + manifest + predict-readiness (T8), fixture test strategy (T2,T5,T8), deps (T1), gitignore/README/iterations-history (T9). ✓
- **Depends on plan `00005`:** provider defaults to `./data`; cache at `./data/cache`. Execute `00005` first.
