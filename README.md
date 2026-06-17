![Version](https://img.shields.io/badge/version-v0.2.0-blue)
![GitHub License](https://img.shields.io/github/license/zhaow-de/zcrypto)
![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https://raw.githubusercontent.com/zhaow-de/zcrypto/develop/pyproject.toml)
![Coveralls](https://img.shields.io/coverallsCoverage/github/zhaow-de/zcrypto)

# zcrypto

Learning-for-Fun project to experience Microsoft Qlib.

<!-- mdformat-toc start --slug=github --maxlevel=3 --minlevel=2 -->

- [Requirements](#requirements)
- [Usage](#usage)
  - [Commands](#commands)

<!-- mdformat-toc end -->

## Requirements<a name="requirements"></a>

`zcrypto` runs Qlib workflows (e.g. `zcrypto example`), which import LightGBM and therefore need the OpenMP runtime installed on your system:

- **macOS:** `brew install libomp`
- **Debian/Ubuntu:** `sudo apt-get install libgomp1`

`zcrypto experiment` additionally needs a local **Redis** instance — qlib's on-disk feature/dataset cache (DiskExpressionCache / DiskDatasetCache) uses Redis for its read/write locks. Start one with:

```bash
./scripts/redis.sh start   # Docker; localhost-only, no auth; data persisted to ../zcrypto-redis-data
./scripts/redis.sh probe   # check that Redis is answering
./scripts/redis.sh stop    # stop the container (data retained)
```

## Usage<a name="usage"></a>

```bash
zcrypto [OPTIONS]          # or: uv run python -m cli [OPTIONS]
```

| Option                                   | Description                                                             |
| ---------------------------------------- | ----------------------------------------------------------------------- |
| `-v`, `--version`                        | Show the application version and exit.                                  |
| `-l`, `--log <path>`                     | Append JSONL logs to this file. If unset, plain-text logs go to stdout. |
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | Log threshold (default `INFO`). Applies to `zcrypto.*` and qlib alike.  |
| `-h`, `--help`                           | Show help and exit.                                                     |

Running with no options prints the help.

### Commands<a name="commands"></a>

| Command   | Description                                                           |
| --------- | --------------------------------------------------------------------- |
| `example` | Run a small offline Qlib ETH-USD strategy backtest demo.              |
| `data`    | Manage the Binance → Qlib dataset (download / verify / backfill / …). |

```bash
zcrypto example                # run the demo backtest
zcrypto example --show-data    # also print the prepared feature-frame head
```

#### `zcrypto data`

Prepare a Qlib-ready dataset from Binance spot klines. Bare `zcrypto data` prints this group's help and exits.

**Status-aware behavior:** Pairs with Binance status `TRADING` are extended to `--to`; non-`TRADING` pairs (e.g. delisted — status `BREAK`, `HALT`, etc.) are downloaded as historical archive only or skipped during backfill.

##### Layout

The dataset uses a **two-root layout**:

- **`./data`** (compiled dataset, default) — Qlib bins (`calendars/`, `instruments/`, `features/`), `index.json`, `.staging/`, and the `.commit-in-progress` crash-recovery marker. This directory is gitignored by `data/.gitignore`; it exists in the repo after clone so `--data-dir`'s default is always present.
- **`BACKUP_DIR`** (positional) — the durable external backup: `raw/` (downloaded-zip mirror, formerly `.raw`) and `snapshots/` (rollback tar.gz archives, formerly `.snapshots`). The de-dotted names reflect that they live outside `./data` entirely.

The staging directory and commit marker stay on `./data` to preserve the same-filesystem atomic-rename invariant; snapshots cross to `BACKUP_DIR` via tar (cross-filesystem safe).

##### `zcrypto data download BACKUP_DIR PAIRS_FILE`

Fetch Binance spot 1d klines from `data.binance.vision`, sha256-validate them, and write/append a Qlib-ready dataset.

| Argument / option                   | Default         | Description                                                                                                                   |
| ----------------------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `BACKUP_DIR` (positional, required) | —               | Backup directory holding the downloaded-zip mirror (`raw/`) and rollback `snapshots/`; created if absent.                     |
| `PAIRS_FILE` (positional, required) | —               | Plain text — one Binance symbol per line (blank lines allowed; symbols are case-normalized to uppercase; ≥1 symbol required). |
| `--data-dir`                        | `./data`        | Compiled qlib dataset directory (default `./data`).                                                                           |
| `--interval`                        | `1d`            | Kline interval. Only `1d` is supported.                                                                                       |
| `--from`                            | `2020-01-01`    | Lower bound (ISO `YYYY-MM-DD`).                                                                                               |
| `--to`                              | yesterday (UTC) | Upper bound (ISO `YYYY-MM-DD`).                                                                                               |
| `--dry-run`                         | off             | Print the fetch plan and exit without writing anything.                                                                       |

```bash
echo BTCUSDT > pairs.txt
zcrypto data download ./bk pairs.txt --data-dir ./data --from 2024-01-01 --to 2024-01-31
zcrypto data download ./bk pairs.txt --dry-run          # preview only
```

**Concurrency:** `data download` fetches up to **8** daily zips in parallel (gentle by default to avoid hammering the data archive). The cap is set by `CliConstants.FETCH_CONCURRENCY` in `cli/constants.py`; tune by editing the constant — there is no env var or CLI flag for this. The convention is that low-change operational config lives in `CliConstants`; high-change-odds config gets a Typer flag.

**Local mirror & recovery:** every verified zip is saved to the `BACKUP_DIR` mirror at `<BACKUP_DIR>/raw`, under a tree that mirrors the remote archive layout plus a year subdir — e.g. `./bk/raw/spot/daily/klines/DOTUSDT/1d/2025/DOTUSDT-1d-2025-10-14.zip`. On a later run a present zip is read from the mirror instead of re-downloaded, so a partial or failed download resumes cheaply rather than starting over. The `raw/` directory lives inside `BACKUP_DIR` and is excluded from snapshots, verification, and the atomic commit. The mirror is trusted as immutable and read without re-checksumming; delete a file (or the tree) to force a re-fetch.

**Missing `.CHECKSUM`:** some recent archive days ship the zip without a sibling `.CHECKSUM`. Rather than fail, the download verifies the zip structurally (it extracts to exactly one parse-able CSV), logs a warning, and continues.

##### `zcrypto data verify`

Re-validate an existing dataset against `index.json` and all invariants. Read-only. Unless `--silent`, it prints a checklist of exactly what was validated (schema, calendar density + sha256, instruments, per-pair bin sha256/size/header and `rows`/`to` cross-checks, orphan scan).

Two dataset-level scans run here:

- **Interior-gap check (fails):** every calendar day between the dataset's first and last day must be covered by at least one pair. A stretch covered by no pair (e.g. two pairs with a listing gap between them that was never bridged by `rename`) is reported and exits non-zero. (This completeness check is specific to the command; the internal post-mutation gate accepts such structurally-valid intermediate states.)
- **Synthetic-day report (informational):** days carrying `NaN` prices — the suspension bars a `rename` writes to bridge a delist→relist gap — are listed per pair. Not a failure.

| Option       | Default  | Description                                                                      |
| ------------ | -------- | -------------------------------------------------------------------------------- |
| `--data-dir` | `./data` | Compiled qlib dataset directory (default `./data`).                              |
| `--silent`   | off      | Print nothing; convey result via exit code only (0 = valid, non-zero = problem). |

```bash
zcrypto data verify                       # validate ./data (default)
zcrypto data verify --data-dir ./data
```

##### `zcrypto data backfill BACKUP_DIR`

Extend every `TRADING` pair in the dataset forward to `--to` (default yesterday UTC). Non-`TRADING` pairs (delisted, halted) are silently skipped. The command is a no-op when all pairs are already caught up or all are non-`TRADING`; in that case no snapshot is written.

| Argument / option                   | Default         | Description                                                                                               |
| ----------------------------------- | --------------- | --------------------------------------------------------------------------------------------------------- |
| `BACKUP_DIR` (positional, required) | —               | Backup directory holding the downloaded-zip mirror (`raw/`) and rollback `snapshots/`; created if absent. |
| `--data-dir`                        | `./data`        | Compiled qlib dataset directory (default `./data`).                                                       |
| `--to`                              | yesterday (UTC) | Extend up to this date (ISO `YYYY-MM-DD`).                                                                |
| `--dry-run`                         | off             | Print the per-pair extension plan and exit without writing.                                               |

```bash
zcrypto data backfill ./bk                               # extend to yesterday
zcrypto data backfill ./bk --to 2024-06-30               # extend to a specific date
zcrypto data backfill ./bk --dry-run                     # preview only
```

##### `zcrypto data delist BACKUP_DIR SYMBOL`

Remove a pair from the dataset. The calendar is conditionally shrunk: if the delisted pair was the earliest or latest in the dataset the calendar is front- or back-trimmed to cover the remaining pairs; a mid-calendar delist that would leave a gap is rejected with an error.

Refuses with an actionable error when: the symbol is not in the index, it is the last pair in the dataset, or removing it would create a non-contiguous calendar gap.

| Argument / option                   | Default  | Description                                                                                               |
| ----------------------------------- | -------- | --------------------------------------------------------------------------------------------------------- |
| `BACKUP_DIR` (positional, required) | —        | Backup directory holding the downloaded-zip mirror (`raw/`) and rollback `snapshots/`; created if absent. |
| `SYMBOL` (positional, required)     | —        | Binance symbol to remove (case-insensitive).                                                              |
| `--data-dir`                        | `./data` | Compiled qlib dataset directory (default `./data`).                                                       |
| `--dry-run`                         | off      | Print the delist plan and exit without writing.                                                           |

```bash
zcrypto data delist ./bk MATICUSDT
zcrypto data delist ./bk MATICUSDT --dry-run      # preview only
```

##### `zcrypto data rename BACKUP_DIR OLD_SYMBOL NEW_SYMBOL`

Relabel a pair. Two variants are detected automatically from the index:

- **Variant 1** — `OLD_SYMBOL` is in the index but `NEW_SYMBOL` is not. The command probes `data.binance.vision` for `NEW_SYMBOL`'s first available archive day, synthesizes any gap between `OLD_SYMBOL`'s last day and that first day as suspension bars (OHLC/VWAP = `NaN`, volume/amount/trades = `0`, `factor = 1.0`), and relabels the dataset entry. The renamed pair's `dates_to` is set to `new_first - 1 day`. `NaN` is qlib's native "suspended / not tradable" marker — its backtest treats those days as untradable, so the gap drops out of returns and indicators instead of injecting fake flat bars.
- **Variant 2** — both `OLD_SYMBOL` and `NEW_SYMBOL` are in the index (e.g. both were downloaded by `data download`). `OLD_SYMBOL`'s historical bins are prepended to `NEW_SYMBOL`'s bins with the same synthetic suspension gap fill in between. `OLD_SYMBOL` is then removed from the index.

Refuses with an error when: `OLD_SYMBOL` is not in the index, `OLD_SYMBOL` equals `NEW_SYMBOL`, `NEW_SYMBOL` is not a valid Binance symbol (exchangeInfo), or (Variant 2) the two ranges overlap.

**Operational precondition.** Run `data backfill` immediately before `data rename` so `OLD_SYMBOL`'s `index.to` reflects its last real trading day. If `index.to` is stale, the synthetic gap fill will silently cover dates when `OLD_SYMBOL` was actually trading — distorting analysis for those dates.

| Argument / option                   | Default  | Description                                                                                               |
| ----------------------------------- | -------- | --------------------------------------------------------------------------------------------------------- |
| `BACKUP_DIR` (positional, required) | —        | Backup directory holding the downloaded-zip mirror (`raw/`) and rollback `snapshots/`; created if absent. |
| `OLD_SYMBOL` (positional, required) | —        | Current symbol name in the index (case-insensitive).                                                      |
| `NEW_SYMBOL` (positional, required) | —        | Replacement symbol name (case-insensitive).                                                               |
| `--data-dir`                        | `./data` | Compiled qlib dataset directory (default `./data`).                                                       |
| `--dry-run`                         | off      | Print the rename plan and exit without writing.                                                           |

```bash
zcrypto data rename ./bk MATICUSDT POLUSDT
zcrypto data rename ./bk MATICUSDT POLUSDT --dry-run   # preview only
```

#### `zcrypto experiment`

Run an end-to-end Qlib pipeline — Alpha158 features (158-factor library, default 2-day-forward label) → LightGBM ranker → TopkDropout long/cash daily backtest → 3-panel Plotly report — and write a predict-ready run bundle. The **recipe is the single swappable moving part**: swap `cli/experiment/recipes/<name>.py` to change the universe, features, model, or strategy parameters and iterate.

> **Prerequisite:** Redis must be running before you invoke this command (`./scripts/redis.sh start`). The command performs a Redis pre-flight check and exits with a clear error if Redis is unreachable.

```bash
zcrypto experiment [--recipe skeleton] [--data-dir ./data] [--out ./runs] [--svg] [--refresh-cache] [--open/--no-open]
```

| Option             | Default                 | Description                                                                             |
| ------------------ | ----------------------- | --------------------------------------------------------------------------------------- |
| `--recipe`         | `skeleton`              | Recipe name to run (see `cli/experiment/recipes/`).                                     |
| `--data-dir`       | `./data`                | Qlib provider directory (the `index.json` / `features/` / `calendars/` tree).           |
| `--out`            | `./runs`                | Root directory for run bundles; each bundle lands at `<out>/<recipe>/<UTC timestamp>/`. |
| `--svg/--no-svg`   | off                     | Also render `report.svg` (requires kaleido).                                            |
| `--refresh-cache`  | off                     | Force-wipe qlib's on-disk feature/dataset cache before the run.                         |
| `--open/--no-open` | on when stdout is a TTY | Open `report.html` in a browser when done. Auto-detected from whether stdout is a TTY.  |

**Run bundle layout** — each run writes a timestamped directory `runs/<recipe>/<UTC-timestamp>/`:

| File                   | Description                                                                                                                                            |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `report.html`          | 3-panel Plotly report: equity vs BTCUSDT buy-and-hold over the test window / trade timeline / full-history context with LUNA+FTX crash periods shaded. |
| `report.svg`           | Static SVG export of the same report (only with `--svg`).                                                                                              |
| `metrics.json`         | Annualized return, max drawdown, information ratio and other backtest metrics.                                                                         |
| `trades.csv`           | Flat trade log (one row per executed order).                                                                                                           |
| `run_meta.json`        | Manifest: recipe, git commit, qlib/lightgbm versions, segments, universe, fee preset, index fingerprint.                                               |
| `recipe_snapshot.json` | Full recipe parameters as a JSON dict (reproducibility).                                                                                               |
| `model.pkl`            | Predict-ready serialized LightGBM model (copied from the per-run MLflow store).                                                                        |
| `mlruns/`              | Per-run MLflow experiment store; inspect with `mlflow ui --backend-store-uri runs/<recipe>/<ts>/mlruns`.                                               |

> **Realistic-expectations caveat:** The default `skeleton` recipe is a naive baseline, **not** a profitable strategy. A cold run over the 2025–2026 test window currently turns 10,000 → ~3,700 USDT and underperforms BTCUSDT buy-and-hold. It exists to validate the pipeline and to be iterated on — see `docs/open-topics/` for the deferred robustness topics (validation rigor, regime overlay, realistic execution, point-in-time universe, paper trading).

```bash
./scripts/redis.sh start                          # ensure Redis is up
zcrypto experiment                                # run with the skeleton recipe
zcrypto experiment --recipe my_recipe             # run a custom recipe
zcrypto experiment --refresh-cache --no-open      # bust the cache; no browser
mlflow ui --backend-store-uri runs/skeleton/<ts>/mlruns   # inspect the MLflow run
```
