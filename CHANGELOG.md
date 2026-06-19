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
