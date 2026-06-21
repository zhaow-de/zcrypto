# Stage-0: passive-beta null + validation harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement
> this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ship the pre-registered `beta_null` recipe + the three Stage-0 harness upgrades (always-vs-null
delta, stationary-bootstrap CIs, trial register → true-count deflated Sharpe), per spec
`docs/specs/00032-stage0-null-and-validation-design.md`. No edge target.

**Architecture:** three independent pure-function builds (bootstrap stats, liquidity schedule, trial
register) land first with full unit coverage; then the `VolWeightedRegimeStrategy` gains a membership
filter and the `beta_null` recipe composes it; then the `stress` command is upgraded to run the null,
compute the paired delta + CIs, and register trials. Everything reuses existing machinery — the only
behavioural seam is the strategy-side monthly membership filter.

**Tech stack:** Python 3.12, qlib, numpy/scipy/pandas, Typer CLI, pytest. uv for all runs.

## Global Constraints

- Frozen `beta_null` params (the pre-registration — copy verbatim): universe = **full liquid PIT set**
  (the strategy selects monthly top-10 by liquidity internally); strategy `VolWeightedRegimeStrategy` with
  `regime_mode="binary"`, `regime_benchmark="BTCUSDT"`, `regime_ma_window=200`, `weight_vol_lookback=30`,
  **`vol_target=0.50`**; model `DummyRegressor` (mean, no alpha bet); **`fee_preset="vip2_bnb"`**;
  `label="Ref($close,-6)/Ref($close,-1)-1"`, `label_horizon_days=6`.
- Liquidity rank: top-10 by **trailing-`lookback_days` mean of `$amount`** (quote dollar-volume), **monthly**
  (`rebalance="MS"`), PIT eligibility = out-of-range names yield NaN/absent `$amount` and rank out.
- Stats live in `cli/experiment/stats.py` (pure numpy/scipy, no qlib). Paired delta CI uses **one shared
  resample index draw** across candidate+null. Deflated Sharpe reads the **cumulative** trial-Sharpe vector,
  de-duped on config hash.
- All new pure functions NaN-guard for `size<2` returning the same shape (match `sharpe`/`psr`).
- TDD: failing test → minimal impl → pass → commit, every task. `uv run ruff check --fix` + `ruff format`
  before each commit. Prefer the fast test subset while iterating.

## File Structure

- Create: `cli/experiment/universe_schedule.py` (pure `liquidity_rank_schedule` + a `D.features` loader)
- Create: `cli/experiment/trials.py` (recipe config hash + append/read trial register)
- Create: `cli/experiment/recipes/beta_null.py` (the frozen recipe)
- Modify: `cli/experiment/stats.py` (+`stationary_bootstrap_ci`, `paired_bootstrap_delta_ci`, private index draw)
- Modify: `cli/experiment/strategies/regime.py` (`VolWeightedRegimeStrategy` membership filter)
- Modify: `cli/experiment/multiseed.py` (surface per-seed daily return series)
- Modify: `cli/stress/command.py` (`--null`, paired delta, CIs, trial register, report + echo)
- Modify: `cli/rank/command.py` (deflated Sharpe reads the cumulative register)
- Modify: `README.md` (`--null` usage), `docs/iterations-history.md` (closeout)
- Tests: `tests/test_experiment_stats.py`, `tests/test_universe_schedule.py` (new),
  `tests/test_trials.py` (new), `tests/test_regime_strategy.py` (or existing strategy test),
  `tests/test_experiment_recipe.py` (drift-guard), `tests/test_multiseed.py`, `tests/test_stress_command.py`

---

### Task 1: Stationary-bootstrap CIs (pure stats)

**Files:** Modify `cli/experiment/stats.py`; Test `tests/test_experiment_stats.py`.

**Interfaces — Produces:**
- `_stationary_bootstrap_indices(n: int, block_len: float, n_resamples: int, rng) -> np.ndarray` (shape
  `n_resamples × n`; Politis–Romano geometric blocks, restart prob `p = 1/block_len`, wrap-around).
- `stationary_bootstrap_ci(returns, *, block_len, n_resamples=1000, statistic=sharpe, alpha=0.05, seed=None) -> dict`
  → `{"point", "lo", "hi", "se", "resamples"}` (point=`statistic(returns)`; lo/hi = `alpha/2`,`1-alpha/2`
  percentiles; se = std of resamples). NaN-shape for `size<2`.
- `paired_bootstrap_delta_ci(returns_cand, returns_null, *, block_len, n_resamples=1000, statistic=sharpe, alpha=0.05, seed=None) -> dict`
  — draws **one** index array per resample (shared via `_stationary_bootstrap_indices`) and reindexes BOTH
  series, then `delta = statistic(cand_rs) - statistic(null_rs)` per resample. Same dict shape; point = the
  paired delta on the originals.

- [ ] **Step 1 — failing tests** in `tests/test_experiment_stats.py`:
  - `seed`-determinism; on iid `np.random.default_rng(0).normal(size=2000)` the bootstrap `se` ≈ Lo-2002
    analytic `sqrt((1+SR**2/2)/n)` within ~25%; an AR(1)/block-correlated series gives a **wider** `se` than
    iid of the same n; `lo < point < hi`.
  - paired: build `null` and `cand = null + small_iid_gap`; assert `paired_bootstrap_delta_ci(...)["hi"-"lo"]`
    **<** the width from independently bootstrapping each and differencing (the pairing-tightens assertion,
    spec Testing); `size<2` → NaN-shape dict.
- [ ] **Step 2 — run, verify red.** `uv run pytest tests/test_experiment_stats.py -q -k bootstrap`
- [ ] **Step 3 — implement** the three functions in `stats.py` (numpy only; reuse module `sharpe`).
- [ ] **Step 4 — green** + `ruff check --fix && ruff format`.
- [ ] **Step 5 — commit** `feat(experiment): add stationary-bootstrap + paired-delta Sharpe CIs`.

### Task 2: Liquidity-rank universe schedule (pure)

**Files:** Create `cli/experiment/universe_schedule.py`; Test `tests/test_universe_schedule.py` (new).

**Interfaces — Produces:**
- `liquidity_rank_schedule(amount_wide: pd.DataFrame, *, top_n=10, lookback_days, rebalance="MS") -> dict[pd.Timestamp, list[str]]`
  — pure: rolling `lookback_days` mean of `$amount` per column, sampled at `rebalance` month-starts,
  `nlargest(top_n)` per point (NaN ranks out). Deterministic (stable tie-break on name).
- `build_liquidity_schedule(universe, data_dir, *, top_n=10, lookback_days, rebalance="MS") -> dict[...]`
  — thin loader: `D.features(list(universe), ["$amount"], freq="day")`, unstack to wide, call the pure fn.
  (Mirrors `regime.py:_build_vol_panel`'s `D.features` pattern.)

- [ ] **Step 1 — failing test** (`tests/test_universe_schedule.py`): synthetic wide `$amount` panel where
  the top-10 by trailing mean is known per month; assert membership + ordering; assert a name with NaN
  before its listing date is absent in early months but present once it ranks (PIT); assert reproducible
  across two calls.
- [ ] **Step 2 — red.** `uv run pytest tests/test_universe_schedule.py -q`
- [ ] **Step 3 — implement** the pure fn (the loader is exercised in Task 5's integration, not unit-tested
  against live qlib here).
- [ ] **Step 4 — green** + ruff. **Step 5 — commit** `feat(experiment): add liquidity-rank universe schedule`.

### Task 3: Trial register + config hash (pure)

**Files:** Create `cli/experiment/trials.py`; Test `tests/test_trials.py` (new).

**Interfaces — Produces:**
- `recipe_config_hash(recipe) -> str` — sha256 of the recipe's frozen, JSON-serialized config (stable key
  ordering; reuse `cli/data/index.py compute_sha256` if it takes bytes, else hashlib).
- `register_trial(path, *, recipe_name, config_hash, sharpe, created) -> None` — append one JSON line to
  `runs/trials.jsonl` (`{"id", "recipe", "config_hash", "sharpe", "created"}`).
- `cumulative_sr_trials(path) -> list[float]` — read all lines, **de-dup on `config_hash`** (last wins),
  return the Sharpe vector for `deflated_sharpe`.

- [ ] **Step 1 — failing test** (`tests/test_trials.py`): append 3 trials (one a duplicate config_hash);
  `cumulative_sr_trials` returns 2 deduped Sharpes; `recipe_config_hash(resolve_recipe("beta_null"))` is
  stable across calls and differs from `resolve_recipe("steady")`. (Use a tmp_path register.)
- [ ] **Step 2 — red.** `uv run pytest tests/test_trials.py -q`
- [ ] **Step 3 — implement.** **Step 4 — green** + ruff. **Step 5 — commit**
  `feat(experiment): add pre-registered trial register + config hash`.

### Task 4: VolWeightedRegimeStrategy monthly membership filter

**Files:** Modify `cli/experiment/strategies/regime.py`; Test `tests/test_regime_strategy.py` (existing
strategy test file, or add one).

**Interfaces — Consumes:** `liquidity_rank_schedule` (Task 2). **Produces:** new kwargs on
`VolWeightedRegimeStrategy.__init__` — `membership_top_n=None`, `membership_lookback_days=None` (None ⇒ no
filter, back-compat for `regime_volweight_majors`). When set, the strategy lazily builds the schedule from
`D.features(self.weight_universe, ["$amount"])` (mirroring `_build_vol_panel`, regime.py:192-198) on first
use, and in `generate_target_weight_position` (regime.py:213-220), after `names = list(score.index)`,
intersects with `_members_for(trade_start_time)` (month-start exact-or-carry-forward, mirroring `_mult_for`).

- [ ] **Step 1 — failing test:** construct the strategy with a stubbed/injected schedule (inject via a
  `membership_schedule` test seam or monkeypatch the lazy builder), feed a `score` Series spanning more
  names than the month's top-10, assert `generate_target_weight_position` weights ONLY the members and
  carries forward between rebalances; assert `membership_top_n=None` leaves behaviour identical to today
  (regression vs `regime_volweight_majors`).
- [ ] **Step 2 — red.** `uv run pytest tests/test_regime_strategy.py -q`
- [ ] **Step 3 — implement** (`_members_for`, lazy schedule build, the intersect line). Keep the regime
  gate + inverse-vol weighting untouched.
- [ ] **Step 4 — green** + ruff. **Step 5 — commit**
  `feat(experiment): add monthly liquidity-membership filter to VolWeightedRegimeStrategy`.

### Task 5: `beta_null` recipe + drift-guard

**Files:** Create `cli/experiment/recipes/beta_null.py`; Test `tests/test_experiment_recipe.py`.

**Interfaces — Consumes:** Tasks 2+4. **Produces:** module-level `RECIPE = Recipe(name="beta_null", ...)`
with the Global-Constraints frozen params; `universe` = the full liquid PIT set (reuse `steady`/
`regime_equalweight`'s universe tuple so Alpha158 materializes all names); `strategy_config.kwargs` adds
`membership_top_n=10, membership_lookback_days=<frozen, e.g. 30>` and `weight_universe`=the full set.

- [ ] **Step 1 — failing drift-guard test** (`tests/test_experiment_recipe.py`): `resolve_recipe("beta_null")`
  has exactly the frozen params (vol_target 0.50, fee_preset vip2_bnb, regime_ma_window 200, binary, top_n
  10, DummyRegressor), and its non-lever fields match the `steady` book (segments/label/account), mirroring
  the Phase-1 drift-guards.
- [ ] **Step 2 — red.** `uv run pytest tests/test_experiment_recipe.py -q -k beta_null`
- [ ] **Step 3 — implement** the recipe. **Step 4 — green** + `uv run python -c "from cli.experiment.recipes.base import resolve_recipe; resolve_recipe('beta_null')"` resolves. ruff.
- [ ] **Step 5 — commit** `feat(experiment): add pre-registered beta_null recipe`.

### Task 6: Surface per-seed daily return series

**Files:** Modify `cli/experiment/multiseed.py`; Test `tests/test_multiseed.py`.

**Interfaces — Produces:** `_holdout_metrics_for_seed` (multiseed.py:237-270) adds the per-seed daily
series to its return dict — `"daily_long"` (= `cost_adj`, the existing net long-only series at :256) and
`"daily_ls"` (= `ls["daily"]`, currently discarded at :261). `run_holdout_seeds` (:273-297) carries them
through in each `per_seed` entry. `summarize_seed_metrics` is unchanged (it only summarizes scalars; the
daily series live alongside, not summarized).

- [ ] **Step 1 — failing test** (`tests/test_multiseed.py`): a `run_holdout_seeds` run on the fixture
  exposes `res["per_seed"][0]["daily_long"]` and `["daily_ls"]` as non-empty pandas Series; `summary`
  scalars unchanged.
- [ ] **Step 2 — red.** **Step 3 — implement** (thread the two series through; don't summarize them).
- [ ] **Step 4 — green** (redis-gated; run with Redis up). ruff. **Step 5 — commit**
  `feat(experiment): surface per-seed daily return series from run_holdout_seeds`.

### Task 7: `stress --null` + paired delta + CIs + trial register + report

**Files:** Modify `cli/stress/command.py`; Test `tests/test_stress_command.py`.

**Interfaces — Consumes:** Tasks 1,3,5,6. **Produces:** `--null` option (`typer.Option("beta_null", "--null")`,
default-on); per window, also `run_holdout_seeds` the null on the same window/seeds; compute per-window
**delta-vs-null** (candidate mean Sharpe − null mean Sharpe) and a **`paired_bootstrap_delta_ci`** on the
pooled per-seed `daily_long` (or mean-across-seeds daily) of candidate vs null; append a trial to
`runs/trials.jsonl` (Task 3) for the candidate and report a **deflated Sharpe** from
`cumulative_sr_trials` (Task 3) → `deflated_sharpe`. Extend `stress_summary.json`: per-window add
`null_sharpe_mean, delta_sharpe, delta_ci{lo,hi,se}`; `aggregate` add `delta_mean_across_windows,
deflated_sharpe`. Console echo adds delta + CI columns + the deflated-Sharpe line. Self-check
(`--recipe beta_null --null beta_null`) → ~0 delta.

- [ ] **Step 1 — failing test** (`tests/test_stress_command.py`): `CliRunner` `stress --recipe beta_null
  --null beta_null --seeds 2` (fixture, redis-gated) → `stress_summary.json` has the new per-window +
  aggregate keys; the self-check `delta_sharpe ≈ 0`; `runs/trials.jsonl` got a line.
- [ ] **Step 2 — red.** **Step 3 — implement** the wiring (reuse the existing per-window loop; add the
  null run + delta + CI + register + report keys + echo). Keep `README` update for Task 9.
- [ ] **Step 4 — green** (redis-gated). ruff. **Step 5 — commit**
  `feat(stress): benchmark vs the beta_null null with paired delta CIs + trial register`.

### Task 8: `rank` deflated Sharpe reads the cumulative register

**Files:** Modify `cli/rank/command.py`; Test `tests/test_rank.py`.

**Interfaces — Consumes:** Task 3. **Produces:** at rank/command.py:71-72, the `sr_trials` fed to
`deflated_sharpe` becomes the **union** of the in-run trial Sharpes and `cumulative_sr_trials(runs/trials.jsonl)`
(deduped), so the deflation reflects the true cumulative trial count + dispersion, not just one invocation.

- [ ] **Step 1 — failing test** (`tests/test_rank.py`): with a seeded `trials.jsonl`, `rank` deflated
  Sharpe uses the larger cumulative trial vector (its DSR ≤ the in-run-only DSR for the same best).
- [ ] **Step 2 — red.** **Step 3 — implement.** **Step 4 — green** + ruff. **Step 5 — commit**
  `feat(rank): deflate Sharpe against the cumulative trial register`.

### Task 9: Closeout — README usage + iterations-history

**Files:** Modify `README.md` (Usage), `docs/iterations-history.md`.

- [ ] **Step 1 — README:** document the `stress --null` option under the Usage section (per
  `.claude/rules/readme-usage.md`; mdformat owns the TOC).
- [ ] **Step 2 — iterations-history:** append the **iter-34** entry — what landed (`beta_null`, the
  liquidity membership filter + schedule, the bootstrap CIs, the trial register + true-count deflated
  Sharpe, the `stress --null` delta), the recorded null yardstick (its OOS Sharpe + bootstrap CI from a
  real `stress --recipe beta_null` run), and that this is Stage-0 (no edge target).
- [ ] **Step 3 — commit** `docs: iter-34 Stage-0 closeout (beta_null null + validation harness)`.

## Iterations-history note

This plan's final task appends the iter-34 entry to `docs/iterations-history.md` (per
`.claude/rules/iterations-history.md`) — authored at closeout with the real recorded null number, not now.
