## v0.5.0 (2026-06-21)

The heart of the Phase-1 research arc (iters 23–32): a regime-overlay strategy family that turns the daily-OHLCV pipeline from a no-edge backtest into a defensible, out-of-sample-robust *defensive* strategy — plus the research write-up that documents the journey and its hard limits.

### 🚀 Features

#### Regime-gated strategy family — from "no edge" to a deployable defensive basket

A sweep of regime-overlay strategies established the project's first out-of-sample-robust result: a regime-gated, inverse-vol-weighted basket of large-cap majors.

- **The gate, fixed and tuned** — the BTC-trend long/cash gate (with volatility targeting) is the first thing in the project that improves risk-adjusted return out-of-sample; faster gates whipsaw, and graded / funding / cross-asset variants add nothing.
  *[#65](https://github.com/zhaow-de/zcrypto/pull/65), [#66](https://github.com/zhaow-de/zcrypto/pull/66), [#67](https://github.com/zhaow-de/zcrypto/pull/67), [#68](https://github.com/zhaow-de/zcrypto/pull/68) by @zhaow-de*
- **The out-of-sample wall** — model-class and label-horizon sweeps confirmed the daily-OHLCV cross-sectional alpha does not survive out-of-sample; the failure is the signal itself, not the features or model.
  *[#69](https://github.com/zhaow-de/zcrypto/pull/69), [#70](https://github.com/zhaow-de/zcrypto/pull/70) by @zhaow-de*
- **Equal-weight beats ML selection** — a gated equal-weight book out-performs the ML-selected one out-of-sample (the cross-sectional selection is net-harmful); curating to large-cap majors with inverse-vol weighting gives the best, most defensible downside protection.
  *[#71](https://github.com/zhaow-de/zcrypto/pull/71), [#72](https://github.com/zhaow-de/zcrypto/pull/72), [#73](https://github.com/zhaow-de/zcrypto/pull/73), [#74](https://github.com/zhaow-de/zcrypto/pull/74) by @zhaow-de*

### 📚 Documentation

#### Phase-1 research summary, recipe docs, and open-topics audit

A comprehensive Phase-1 research narrative (iters 1–33) with academic figures and the per-iteration decision log; all 21 recipe docstrings leveled to one consistent structure carrying their measured verdicts; and an open-topics audit that resolves the topics made moot by the "OHLCV/regime vein is exhausted" conclusion. Also bundles a logging deprecation fix and a generalized autonomous research-loop skill.

*[#75](https://github.com/zhaow-de/zcrypto/pull/75), [#78](https://github.com/zhaow-de/zcrypto/pull/78) by @zhaow-de*

### 🔧 CI/Build

#### Dependency updates

Routine dependency bumps: pydantic-settings, msgpack, jupyterlab, ruff-pre-commit, and actions/checkout (v6 → v7).

*[#62](https://github.com/zhaow-de/zcrypto/pull/62), [#63](https://github.com/zhaow-de/zcrypto/pull/63), [#64](https://github.com/zhaow-de/zcrypto/pull/64), [#76](https://github.com/zhaow-de/zcrypto/pull/76), [#77](https://github.com/zhaow-de/zcrypto/pull/77) by @dependabot*

## v0.4.0 (2026-06-21)

The research arc from a single skeleton recipe to a cost-realistic, survivorship-free, multi-signal experiment platform — plus the honest out-of-sample verdict on its first profitable result, and a new unattended autonomous-research mode.

### 🚀 Features

#### Walk-forward out-of-sample validation (`zcrypto stress`)
New `zcrypto stress` subcommand rolls the train→test split across annual out-of-sample windows (each trained only on prior data) and reports per-window long-only vs market-neutral Sharpe — so an edge measured on the dev holdout can be checked on never-tuned periods. Its first use refuted the iter-21 long/short edge out-of-sample (positive only on the dev-seen 2025 window).

*[#57](https://github.com/zhaow-de/zcrypto/pull/57) by @zhaow-de*

#### Market-neutral long/short edge evaluation
A dollar-neutral top-k/bottom-k spread evaluator over the cross-sectional alpha, surfacing per-seed `ls_sharpe`/`ls_ending` in the multi-seed holdout — the project's first profitable backtest result (since shown to be dev-holdout-specific by `zcrypto stress`).

*[#55](https://github.com/zhaow-de/zcrypto/pull/55) by @zhaow-de*

#### Funding-carry feature + recipes
Turns Binance perpetual funding into a focused 5-column carry feature set (level, z-score, cross-sectional rank, moving average, change), with `funding_steady` / `funding_crossasset_steady` recipes and a multi-seed A/B edge test.

*[#54](https://github.com/zhaow-de/zcrypto/pull/54) by @zhaow-de*

#### Realistic execution costs by default
Calibrated qlib `impact_cost` plus a maker-fill haircut (calibrated from an aggTrades sample) are now the default cost model, with a `--fees-only` baseline for comparison.

*[#52](https://github.com/zhaow-de/zcrypto/pull/52) by @zhaow-de*

#### Point-in-time universe + survivorship re-measure
Adds a `--pit-universe` lever and the Terra/LUNA blow-up to the dataset, and re-measures every recipe survivor-vs-PIT.

*[#51](https://github.com/zhaow-de/zcrypto/pull/51) by @zhaow-de*

#### Execution-realism data (aggTrades sample)
Acquires a Binance aggTrades sample as the basis for slippage / maker-fill cost calibration.

*[#49](https://github.com/zhaow-de/zcrypto/pull/49) by @zhaow-de*

#### Survivorship-free delisted-pair data
Adds delisted USDT pairs so the traded universe no longer suffers survivorship bias.

*[#48](https://github.com/zhaow-de/zcrypto/pull/48) by @zhaow-de*

#### Perpetual funding-rate data foundation
Makes Binance USDT-perp funding a first-class qlib field (`$funding`), woven into every `zcrypto data` subcommand with an idempotent retrofit.

*[#47](https://github.com/zhaow-de/zcrypto/pull/47) by @zhaow-de*

#### Deterministic experiments + multi-seed holdout
Adds `--seeds N` / `--deterministic`, so holdout verdicts are reported as a distribution across seeds instead of a single noisy run.

*[#46](https://github.com/zhaow-de/zcrypto/pull/46) by @zhaow-de*

#### Pluggable feature handler + richer-signal experiment
A `feature_config` seam (Alpha158/360 plus a custom cross-asset handler) for richer-signal experiments.

*[#45](https://github.com/zhaow-de/zcrypto/pull/45) by @zhaow-de*

#### Strategy scaffold seam, BTC-regime overlay, walk-forward
Adds a strategy seam to the scaffold, a BTC-trend regime overlay (long/cash gating), and a walk-forward retraining mode.

*[#43](https://github.com/zhaow-de/zcrypto/pull/43) by @zhaow-de*

#### `steady` recipe
A low-turnover, longer-horizon, regularized recipe.

*[#41](https://github.com/zhaow-de/zcrypto/pull/41) by @zhaow-de*

### 📚 Documentation

#### `/research-loop` unattended autonomous-research skill
A user-invocable skill that runs full brainstorm→spec→plan→execute→verdict→merge research iterations autonomously — recording each decision to `.tmp/decisions.md` and stopping only at a configurable time-gate.

*[#59](https://github.com/zhaow-de/zcrypto/pull/59) by @zhaow-de*

#### Open-topics tracking
Registers T0016 (first-class market-neutral L/S strategy) and T0015 (gross holdout `ending_value`), and archives resolved topics with an updated index and convention rule.

*[#56](https://github.com/zhaow-de/zcrypto/pull/56), [#53](https://github.com/zhaow-de/zcrypto/pull/53), [#50](https://github.com/zhaow-de/zcrypto/pull/50) by @zhaow-de*

### 🔧 CI/Build

- Ignore the `.tmp` scratch directory. *[#58](https://github.com/zhaow-de/zcrypto/pull/58) by @zhaow-de*
- Bump ruff 0.15.17 → 0.15.18. *[#42](https://github.com/zhaow-de/zcrypto/pull/42) by @app/dependabot*

### 📦 Other Changes

- Rename the open-topics serial scheme (`00001` → `T0001`). *[#44](https://github.com/zhaow-de/zcrypto/pull/44) by @zhaow-de*
- Back-merge v0.3.1 into develop. *[#40](https://github.com/zhaow-de/zcrypto/pull/40) by @zhaow-de*

## v0.3.1 (2026-06-19)

### 🐛 Bug Fixes

#### GitHub Release notes are now populated correctly

The `/release` tooling reads each GitHub Release's notes from the version tag instead of the working tree, so a published Release always carries its changelog section (previously the notes could be published empty).

*[#38](https://github.com/zhaow-de/zcrypto/pull/38) by @zhaow-de*

## v0.3.0 (2026-06-19)

### ⚠️ Breaking Changes

#### `zcrypto data` directory layout

The `zcrypto data` commands no longer take a positional output directory. The compiled Qlib dataset now lives at `--data-dir` (default `./data`), and the durable backup — the downloaded-zip mirror and rollback snapshots — at `--backup-dir`; both also resolve from the new `zcrypto.toml`. A one-time migration (move the compiled dirs into `./data`; rename `.raw`→`raw` and `.snapshots`→`snapshots` in the backup dir) is documented in the README.

*[#25](https://github.com/zhaow-de/zcrypto/pull/25) by @zhaow-de*

### 🚀 Features

#### `zcrypto experiment` — end-to-end Qlib backtest harness

A new `zcrypto experiment --recipe <name>` runs a full Qlib pipeline (Alpha158 features → LightGBM ranker → daily long/cash backtest) and writes a run bundle: a 3-panel Plotly report, metrics, trades, and a predict-ready model. The "recipe" is the single swappable knob you change to experiment; a deliberately naive `skeleton` baseline ships to build on. Requires a local Redis (`scripts/redis.sh start`) for Qlib's disk cache.

*[#26](https://github.com/zhaow-de/zcrypto/pull/26) by @zhaow-de*

#### Rigorous validation by default (CPCV)

`zcrypto experiment` now runs combinatorial purged cross-validation (with purge + embargo) by default, reporting an out-of-sample Sharpe distribution over train+validation while holding the test window as an untouched final holdout. `--quick` opts back into the single fast run.

*[#32](https://github.com/zhaow-de/zcrypto/pull/32) by @zhaow-de*

#### Overfitting diagnostics: PSR, deflated Sharpe, and `zcrypto rank`

Every run now reports a Probabilistic Sharpe Ratio (PSR). The new `zcrypto rank` command treats each saved run as a trial and reports the deflated Sharpe ratio of the best trial (corrected for how many you've tried) plus the probability of backtest overfitting (PBO) — so you can tell whether a good-looking Sharpe survives multiple-testing bias.

*[#34](https://github.com/zhaow-de/zcrypto/pull/34) by @zhaow-de*

#### Honest survivorship caveat on every experiment run

Experiment reports, stdout, and `run_meta.json` now carry a survivorship caveat: the universe is only today's surviving pairs, so results are optimistically inflated. It's surfaced as a concise pointer to the tracked open topic rather than left as a silent gap.

*[#33](https://github.com/zhaow-de/zcrypto/pull/33) by @zhaow-de*

#### App-level `zcrypto.toml` configuration

Dataset directories and fetch-tuning knobs now live in a committed `zcrypto.toml`. Directories resolve flag → config → error (no hidden default), and the operational fetch constants became an overridable `[zcrypto.fetch]` table.

*[#31](https://github.com/zhaow-de/zcrypto/pull/31) by @zhaow-de*

### 📦 Other Changes

#### Console logs now show `extra` fields (plus internal cleanup)

Plain-text console logs now append each record's structured `extra` as `key=value` pairs, matching what the JSON logs already carry. The same PR relocates `rank` into its own package and trims the project's contributor docs — no user-visible CLI change.

*[#35](https://github.com/zhaow-de/zcrypto/pull/35) by @zhaow-de*

#### Dependency updates

Routine bumps: tornado 6.5.7, starlette 1.3.1, aiohttp 3.14.1, cryptography 48.0.1, pytest 9.1.0, and ruff / ruff-pre-commit 0.15.17.

*[#30](https://github.com/zhaow-de/zcrypto/pull/30), [#29](https://github.com/zhaow-de/zcrypto/pull/29), [#28](https://github.com/zhaow-de/zcrypto/pull/28), [#27](https://github.com/zhaow-de/zcrypto/pull/27), [#24](https://github.com/zhaow-de/zcrypto/pull/24), [#23](https://github.com/zhaow-de/zcrypto/pull/23), [#22](https://github.com/zhaow-de/zcrypto/pull/22) by @dependabot*

## v0.2.0 (2026-06-11)

### 🚀 Features

#### iter-5 — backfill, delist, rename, status-aware download/backfill

Completes the `zcrypto data` command suite with three new subcommands: `backfill` extends every pair in your dataset to yesterday's data, `delist` removes a pair with automatic calendar trimming, and `rename` merges a delisted pair's history into its successor (e.g. MATICUSDT → POLUSDT) with proper suspension bars for any listing gap. All four data commands now share a unified crash-recovery harness and support `--dry-run`. Download and backfill are now status-aware: delisted/halted pairs are archived automatically instead of erroring.

*[#16](https://github.com/zhaow-de/zcrypto/pull/16) by @zhaow-de*

### 🐛 Bug Fixes

#### iter-4 — data download & verify

Adds `zcrypto data download` (Binance spot daily klines → validated Qlib dataset) and `zcrypto data verify` (read-only dataset re-validation). Also includes HTTP timeout/retry hardening, concurrent fetching, snapshot-based crash recovery, and the per-commit reviewer-trailer convention.

*[#14](https://github.com/zhaow-de/zcrypto/pull/14) by @zhaow-de*

### 📚 Documentation

#### make review mandatory for every Claude-authored feature/fix commit

Codifies that every Claude-authored commit on a feature/fix branch must be reviewed by a separate subagent before push — no exceptions for "trivial" commits.

*[#17](https://github.com/zhaow-de/zcrypto/pull/17) by @zhaow-de*

#### track Reviewed-by per-commit with amend-while-local workflow

Switches reviewer attribution from a single closeout-commit aggregation to per-commit `Reviewed-by:` trailers, preserving which reviewer covered which slice across long iterations.

*[#15](https://github.com/zhaow-de/zcrypto/pull/15) by @zhaow-de*

#### park pandas concat-with-empty FutureWarning as open-topic T0001

Tracks a benign pandas `FutureWarning` from the backfill staging step as an open topic so it isn't lost before a future pandas upgrade.

*[#19](https://github.com/zhaow-de/zcrypto/pull/19) by @zhaow-de*

## v0.1.1 (2026-06-08)

### 🐛 Bug Fixes

#### auto-merge release PRs and add local-cleanup step to /release

The `/release` skill now runs end-to-end without pausing for manual review or merge steps. Release PRs and back-merge PRs are merged automatically once GitHub marks them ready; after publishing, the skill fast-forwards both local branches, removes the temporary release and back-merge branches, and prunes stale remote-tracking refs.

*[#11](https://github.com/zhaow-de/zcrypto/pull/11) by @zhaow-de*

## v0.1.0 (2026-06-08)

### 🚀 Features

#### iter-1 — Qlib ETH-USD example subcommand

Adds a new `zcrypto example` subcommand that runs a self-contained offline Qlib strategy experiment on a bundled crypto dataset, producing annualized-return, information-ratio, and max-drawdown metrics for a LinearModel + TopkDropout backtest over six coins.

*[#1](https://github.com/zhaow-de/zcrypto/pull/1) by @zhaow-de*

#### iter-2 — general JSON/plain-text logger

Adds project-wide structured logging: plain text to stdout by default, or JSONL to a file via the new `-l/--log <path>` flag; log level is configurable via `--log-level`. Qlib's own log output is captured in both modes so it never bypasses the CLI's output.

*[#5](https://github.com/zhaow-de/zcrypto/pull/5) by @zhaow-de*

#### iter-3 — open-topics rule

Introduces a park-for-later convention for tracking follow-up topics: the agent proposes a topic (with mandatory user approval) and it lands as a serial-numbered markdown file in `docs/open-topics/` with open/resolved status and an auto-maintained index.

*[#3](https://github.com/zhaow-de/zcrypto/pull/3) by @zhaow-de*

### 🐛 Bug Fixes

#### contain qlib's relative-path FileLock leak in run_experiment

Fixed an upstream pyqlib 0.9.7 bug where running `zcrypto example` (or its tests) would litter the project directory with nested `private/var/folders/…` scaffolding left behind by qlib's MLflow FileLock implementation.

*[#4](https://github.com/zhaow-de/zcrypto/pull/4) by @zhaow-de*

#### git-init the qlib chdir tempdir to silence _log_uncommitted_code noise

Fixed spurious `git: not a git repository` stderr output and "Fail to log the uncommitted code" log records that appeared whenever `zcrypto example` ran inside the temporary directory workaround introduced in the previous fix.

*[#7](https://github.com/zhaow-de/zcrypto/pull/7) by @zhaow-de*

#### update agent skill model

Fixed incorrect model alias in the `dependabot` and `merge-pr` agent skill configurations, replacing the non-canonical `claude-haiku` value with the correct `haiku` alias.

*[#2](https://github.com/zhaow-de/zcrypto/pull/2) by @zhaow-de*

### 📦 Other Changes

#### allow model invocation for merge-pr and release skills

The `merge-pr` and `release` skills can now be invoked programmatically from subagent prompts in addition to being typed as slash commands — useful for automated and agentic workflows.

*[#8](https://github.com/zhaow-de/zcrypto/pull/8) by @zhaow-de*

#### move gen_example_data.py under cli/example/scripts

Moved the development-only data generator script next to the example subcommand it supports; it is excluded from the published wheel and coverage report.

*[#6](https://github.com/zhaow-de/zcrypto/pull/6) by @zhaow-de*

## v0.0.0 (2026-06-07)


- chore: initial commit
