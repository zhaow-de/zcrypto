# Iterations history

Per-iteration changelog of the zcrypto project. New entries are appended at the bottom by Claude Code as the final task of each iteration's implementation plan; each entry is a `## <YYYY-MM-DD> — <heading>` section with a bullet list (one bullet per feature/change/fix). CLAUDE.md's "Project state notes" section points here.

## 2026-06-07 — iter-1: `example` Qlib backtest subcommand

- Added `zcrypto example`: a self-contained, **offline** Qlib strategy experiment on a tiny bundled crypto dataset — the project's first real Qlib wiring (`qlib.init` was previously absent).
- `cli/example/dataset.py` `build_provider` writes Qlib's file format (`calendars/day.txt`, `instruments/all.txt`, `features/<coin>/<field>.day.bin` as little-endian float32 with a start-index header) from an OHLCV CSV/`.csv.gz`. Each instrument's bin spans the **full calendar** (absent dates written as NaN) so multi-symbol datasets with differing date sets can never silently misalign.
- `cli/example/workflow.py` `run_experiment` runs the pipeline: ~6-feature `QlibDataLoader` handler + numpy-only `LinearModel` (OLS) → `SignalRecord`/`PortAnaRecord` backtest with `TopkDropoutStrategy(topk=2, n_drop=1)` over 6 coins (`REG_US`, `deal_price=close`, costs 0.0005/0.0015, benchmark `ETHUSD`); returns annualized-return / information-ratio / max-drawdown for strategy-absolute and excess-vs-ETH (with/without cost). Sets `MLFLOW_ALLOW_FILE_STORE=true` (MLflow ≥2 file store) and uses backtest `end_time = TEST end − 1 day` (Qlib needs a trading day after the last order to execute).
- `cli/example/command.py` runs everything inside a `TemporaryDirectory` (the Qlib binary data **and** the MLflow recorder are ephemeral; nothing persists in the repo). Heavy imports are deferred so `zcrypto --version` stays fast. `--show-data/--no-show-data` prints the prepared feature-frame head.
- Bundled data: `cli/example/data/crypto_ohlcv.csv.gz` — **gzip-compressed** (~40 KB) daily OHLCV, 6 coins (BTC/ETH/BNB/SOL/XRP/ADA), window `2025-12-01`..`2026-05-31` (182 dates each), generated one-off by dev-only `scripts/gen_example_data.py` (`yfinance`; not a project dependency, not shipped). `build_provider` reads the gzip transparently via pandas; hatchling ships the file in the wheel.
- `README.md`: added a `## Requirements` section (OpenMP runtime — `brew install libomp` / `apt-get install libgomp1`, required because Qlib imports LightGBM) and documented the `example` command under `## Usage`.
- Tests use seeded synthetic data (no network): `tests/test_example_dataset.py` (binary round-trip + staggered multi-symbol alignment), `tests/test_example_workflow.py` (finite-metrics integration), `tests/test_example_command.py` (CLI smoke). Full suite 10 passed, 98% coverage.

## 2026-06-08 — iter-3: open-topics rule

- Added `.claude/rules/open-topics.md`: a park-for-later convention for topics worth follow-up. The agent **must always ask the user** before creating any topic file; the natural mechanism is `AskUserQuestion` offering approve / amend / skip, with the proposed file body shown inline for review.
- Topic files live at `docs/open-topics/<NNNNN>-<slug>.md` with `<NNNNN>` a 5-digit zero-padded counter independent of `docs/specs/` and `docs/plans/`. Each file carries YAML front-matter `status: open` (closed in place by flipping to `status: resolved`) and a fixed body shape: `# <Title>`, `## Context — what`, `## Why this matters`, `## Findings so far`, `## Suggested next steps`.
- Added `docs/open-topics/README.md` as the index, split into `## Open` and `## Resolved` subsections. Each bullet is a link + one-sentence description; new entries append to the end of their section, so `## Open` is in serial order and `## Resolved` is in resolution order. mdformat manages the TOC (per-file `--maxlevel=2 --minlevel=2`), so only the two section headers appear.
- Expanded the `mdformat` pre-commit hook's `files:` pattern via the verbose `(?x)` form so it now covers both `README.md` and `docs/open-topics/README.md`; specs/plans Markdown and the rule files remain untouched.
- Cross-referenced the new rule in `CLAUDE.md`'s **Conventions** roll-call line, and fixed a pre-existing omission by also adding `spec-plan-locations.md` so all seven rule files are enumerated.
- No code touched; existing pytest suite unchanged (10 passed). `uv run pre-commit run --all-files` is green.
