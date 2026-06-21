![Version](https://img.shields.io/badge/version-v0.5.0-blue)
![GitHub License](https://img.shields.io/github/license/zhaow-de/zcrypto)
![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https://raw.githubusercontent.com/zhaow-de/zcrypto/develop/pyproject.toml)
![Coveralls](https://img.shields.io/coverallsCoverage/github/zhaow-de/zcrypto)

# zcrypto

Learning-for-Fun project to experience Microsoft Qlib.

<!-- mdformat-toc start --slug=github --maxlevel=4 --minlevel=2 -->

- [Requirements](#requirements)
- [Usage](#usage)
  - [Configuration](#configuration)
    - [`[zcrypto]`: dataset paths](#zcrypto-dataset-paths)
    - [`[zcrypto.fetch]`: operational tuning](#zcryptofetch-operational-tuning)
  - [Commands](#commands)
    - [`zcrypto data`](#zcrypto-data)
    - [`zcrypto experiment`](#zcrypto-experiment)
    - [`zcrypto rank`](#zcrypto-rank)
    - [`zcrypto stress`](#zcrypto-stress)

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

### Configuration<a name="configuration"></a>

`zcrypto` reads configuration from **`zcrypto.toml`** in the current working directory (the repo root when running from the checkout). The file is committed with working defaults.

#### `[zcrypto]`: dataset paths<a name="zcrypto-dataset-paths"></a>

```toml
[zcrypto]
data_dir = "data"               # compiled Qlib dataset (calendars/, instruments/, features/, index.json)
backup_dir = "../zcrypto-data"  # durable backup root (raw/ mirror + snapshots/)
```

Paths resolve via **flag → config → error**: if a path is neither passed as a CLI flag nor set in `zcrypto.toml`, the command exits immediately with a clear error message (`ERROR: no <name> configured — set [zcrypto].<name> in zcrypto.toml or pass --<flag> <path>`). There is no built-in fallback.

#### `[zcrypto.fetch]`: operational tuning<a name="zcryptofetch-operational-tuning"></a>

```toml
[zcrypto.fetch]
fetch_concurrency = 8              # max parallel HTTP fetches in `data download`
http_timeout_head_secs = 5         # socket timeout for HEAD / small-body requests
http_timeout_get_secs = 60         # socket timeout for daily-zip GETs
http_retry_attempts = 3            # total attempts per HTTP call (transient failures)
fetch_progress_log_interval = 50   # emit a progress log every N completed (pair, date)
backfill_right_edge_grace_days = 7 # right-edge absence tolerated before delist/rename hint
rename_synth_warn_days = 7         # synthetic-gap-fill threshold for a louder rename warning
```

Each key overrides a built-in default. Omit a key (or the entire `[zcrypto.fetch]` table) to keep the default shown above.

### Commands<a name="commands"></a>

| Command      | Description                                                           |
| ------------ | --------------------------------------------------------------------- |
| `example`    | Run a small offline Qlib ETH-USD strategy backtest demo.              |
| `data`       | Manage the Binance → Qlib dataset (download / verify / backfill / …). |
| `experiment` | Run an end-to-end Qlib pipeline and write a run bundle.               |
| `rank`       | Rank persisted run bundles as trials; report deflated Sharpe + PBO.   |

```bash
zcrypto example                # run the demo backtest
zcrypto example --show-data    # also print the prepared feature-frame head
```

#### `zcrypto data`<a name="zcrypto-data"></a>

Prepare a Qlib-ready dataset from Binance spot klines. Bare `zcrypto data` prints this group's help and exits.

**Status-aware behavior:** Pairs with Binance status `TRADING` are extended to `--to`; non-`TRADING` pairs (e.g. delisted — status `BREAK`, `HALT`, etc.) are downloaded as historical archive only or skipped during backfill.

**Funding rates (`$funding`):** alongside OHLCV, each instrument also carries a `$funding` field — the daily-summed Binance USDT-perpetual funding rate (the carry signal), fetched from the Binance Vision `futures/um/monthly/fundingRate` archives and aligned same-day with `$close`. It is handled transparently by every subcommand: `download`/`backfill` fetch and write it, `verify` reports its per-coin coverage, `delist` removes it, and `rename` carries it across the old→new symbol. The spot↔perp mapping is mostly identity, with `PEPE`→`1000PEPEUSDT` and a MATIC→POL time-split; instruments without a perp (or before its launch) read `NaN`. No extra flags — funding rides the normal data lifecycle.

##### Layout

The dataset uses a **two-root layout**:

- **`--data-dir`** (compiled dataset) — Qlib bins (`calendars/`, `instruments/`, `features/`), `index.json`, `.staging/`, and the `.commit-in-progress` crash-recovery marker. Defaults to `[zcrypto].data_dir` in `zcrypto.toml` (committed default: `./data`).
- **`--backup-dir`** (durable external backup) — `raw/` (downloaded-zip mirror) and `snapshots/` (rollback tar.gz archives). Defaults to `[zcrypto].backup_dir` in `zcrypto.toml` (committed default: `../zcrypto-data`).

The staging directory and commit marker stay on `data-dir` to preserve the same-filesystem atomic-rename invariant; snapshots cross to `backup-dir` via tar (cross-filesystem safe).

##### `zcrypto data download PAIRS_FILE`

Fetch Binance spot 1d klines from `data.binance.vision`, sha256-validate them, and write/append a Qlib-ready dataset.

| Argument / option                   | Default                        | Description                                                                                                                   |
| ----------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `PAIRS_FILE` (positional, required) | —                              | Plain text — one Binance symbol per line (blank lines allowed; symbols are case-normalized to uppercase; ≥1 symbol required). |
| `--data-dir`                        | `[zcrypto].data_dir` in toml   | Compiled qlib dataset directory.                                                                                              |
| `--backup-dir`                      | `[zcrypto].backup_dir` in toml | Backup dir (raw/ + snapshots/); created if absent.                                                                            |
| `--interval`                        | `1d`                           | Kline interval. Only `1d` is supported.                                                                                       |
| `--from`                            | `2020-01-01`                   | Lower bound (ISO `YYYY-MM-DD`).                                                                                               |
| `--to`                              | yesterday (UTC)                | Upper bound (ISO `YYYY-MM-DD`).                                                                                               |
| `--dry-run`                         | off                            | Print the fetch plan and exit without writing anything.                                                                       |
| `--allow-interior-gaps`             | off                            | Fill a 404 inside a pair's resolved `[from, to]` range with a NaN suspension row (each gap day logged) instead of erroring.   |

```bash
echo BTCUSDT > pairs.txt
zcrypto data download pairs.txt --from 2024-01-01 --to 2024-01-31   # dirs from zcrypto.toml
zcrypto data download pairs.txt --backup-dir ./bk --data-dir ./data  # explicit overrides
zcrypto data download pairs.txt --dry-run                            # preview only
```

**Concurrency:** `data download` fetches up to **8** daily zips in parallel (gentle by default to avoid hammering the data archive). The fetch knobs live in the `[zcrypto.fetch]` table of `zcrypto.toml` (`fetch_concurrency`, `http_timeout_head_secs`, `http_timeout_get_secs`, `http_retry_attempts`, `fetch_progress_log_interval`, `backfill_right_edge_grace_days`, `rename_synth_warn_days`); each overrides a built-in default.

**Local mirror & recovery:** every verified zip is saved to the `--backup-dir` mirror at `<backup-dir>/raw`, under a tree that mirrors the remote archive layout plus a year subdir — e.g. `./bk/raw/spot/daily/klines/DOTUSDT/1d/2025/DOTUSDT-1d-2025-10-14.zip`. On a later run a present zip is read from the mirror instead of re-downloaded, so a partial or failed download resumes cheaply rather than starting over. The `raw/` directory lives inside `backup-dir` and is excluded from snapshots, verification, and the atomic commit. The mirror is trusted as immutable and read without re-checksumming; delete a file (or the tree) to force a re-fetch.

**Missing `.CHECKSUM`:** some recent archive days ship the zip without a sibling `.CHECKSUM`. Rather than fail, the download verifies the zip structurally (it extracts to exactly one parse-able CSV), logs a warning, and continues.

**Interior gaps (`--allow-interior-gaps`):** by default a 404 strictly inside a pair's resolved `[from, to]` range is a hard error — a genuine archive problem that should not be silently tolerated. Pass `--allow-interior-gaps` to instead fill each such day with a NaN suspension row (OHLC/VWAP `NaN` — qlib's not-tradable marker — volume-like `0.0`, `factor` `1.0`, the same synthetic row `rename` uses for its gap fill), logging every gap day as a warning. This is for deliberately acquiring a trading-halted pair — e.g. FTT, whose Binance archive has a 404 hole at `2022-11-16` from the FTX-collapse halt. Routine `download`/`backfill` leave the flag off and stay strict.

##### `zcrypto data verify`

Re-validate an existing dataset against `index.json` and all invariants. Read-only. Unless `--silent`, it prints a checklist of exactly what was validated (schema, calendar density + sha256, instruments, per-pair bin sha256/size/header and `rows`/`to` cross-checks, orphan scan).

Two dataset-level scans run here:

- **Interior-gap check (fails):** every calendar day between the dataset's first and last day must be covered by at least one pair. A stretch covered by no pair (e.g. two pairs with a listing gap between them that was never bridged by `rename`) is reported and exits non-zero. (This completeness check is specific to the command; the internal post-mutation gate accepts such structurally-valid intermediate states.)
- **Synthetic-day report (informational):** days carrying `NaN` prices — the suspension bars a `rename` writes to bridge a delist→relist gap — are listed per pair. Not a failure.

| Option       | Default                      | Description                                                                      |
| ------------ | ---------------------------- | -------------------------------------------------------------------------------- |
| `--data-dir` | `[zcrypto].data_dir` in toml | Compiled qlib dataset directory.                                                 |
| `--silent`   | off                          | Print nothing; convey result via exit code only (0 = valid, non-zero = problem). |

```bash
zcrypto data verify                       # validate dir from zcrypto.toml
zcrypto data verify --data-dir ./data
```

##### `zcrypto data backfill`

Extend every `TRADING` pair in the dataset forward to `--to` (default yesterday UTC). Non-`TRADING` pairs (delisted, halted) are silently skipped. The command is a no-op when all pairs are already caught up or all are non-`TRADING`; in that case no snapshot is written.

| Argument / option | Default                        | Description                                                 |
| ----------------- | ------------------------------ | ----------------------------------------------------------- |
| `--data-dir`      | `[zcrypto].data_dir` in toml   | Compiled qlib dataset directory.                            |
| `--backup-dir`    | `[zcrypto].backup_dir` in toml | Backup dir (raw/ + snapshots/); created if absent.          |
| `--to`            | yesterday (UTC)                | Extend up to this date (ISO `YYYY-MM-DD`).                  |
| `--dry-run`       | off                            | Print the per-pair extension plan and exit without writing. |

```bash
zcrypto data backfill                                    # extend to yesterday (dirs from zcrypto.toml)
zcrypto data backfill --to 2024-06-30                    # extend to a specific date
zcrypto data backfill --backup-dir ./bk --data-dir ./data --to 2024-06-30  # explicit overrides
zcrypto data backfill --dry-run                          # preview only
```

##### `zcrypto data drop SYMBOL`

Remove a pair from the dataset (e.g. a mistaken or unwanted entry). The calendar is conditionally shrunk: if the dropped pair was the earliest or latest in the dataset the calendar is front- or back-trimmed to cover the remaining pairs; a removal that would leave a mid-calendar gap is rejected with an error.

Refuses with an actionable error when: the symbol is not in the index, it is the last pair in the dataset, or removing it would create a non-contiguous calendar gap.

| Argument / option               | Default                        | Description                                        |
| ------------------------------- | ------------------------------ | -------------------------------------------------- |
| `SYMBOL` (positional, required) | —                              | Binance symbol to remove (case-insensitive).       |
| `--data-dir`                    | `[zcrypto].data_dir` in toml   | Compiled qlib dataset directory.                   |
| `--backup-dir`                  | `[zcrypto].backup_dir` in toml | Backup dir (raw/ + snapshots/); created if absent. |
| `--dry-run`                     | off                            | Print the drop plan and exit without writing.      |

```bash
zcrypto data drop MATICUSDT                              # dirs from zcrypto.toml
zcrypto data drop MATICUSDT --backup-dir ./bk --data-dir ./data  # explicit overrides
zcrypto data drop MATICUSDT --dry-run                    # preview only
```

##### `zcrypto data rename OLD_SYMBOL NEW_SYMBOL`

Relabel a pair. Two variants are detected automatically from the index:

- **Variant 1** — `OLD_SYMBOL` is in the index but `NEW_SYMBOL` is not. The command probes `data.binance.vision` for `NEW_SYMBOL`'s first available archive day, synthesizes any gap between `OLD_SYMBOL`'s last day and that first day as suspension bars (OHLC/VWAP = `NaN`, volume/amount/trades = `0`, `factor = 1.0`), and relabels the dataset entry. The renamed pair's `dates_to` is set to `new_first - 1 day`. `NaN` is qlib's native "suspended / not tradable" marker — its backtest treats those days as untradable, so the gap drops out of returns and indicators instead of injecting fake flat bars.
- **Variant 2** — both `OLD_SYMBOL` and `NEW_SYMBOL` are in the index (e.g. both were downloaded by `data download`). `OLD_SYMBOL`'s historical bins are prepended to `NEW_SYMBOL`'s bins with the same synthetic suspension gap fill in between. `OLD_SYMBOL` is then removed from the index.

Refuses with an error when: `OLD_SYMBOL` is not in the index, `OLD_SYMBOL` equals `NEW_SYMBOL`, `NEW_SYMBOL` is not a valid Binance symbol (exchangeInfo), or (Variant 2) the two ranges overlap.

**Operational precondition.** Run `data backfill` immediately before `data rename` so `OLD_SYMBOL`'s `index.to` reflects its last real trading day. If `index.to` is stale, the synthetic gap fill will silently cover dates when `OLD_SYMBOL` was actually trading — distorting analysis for those dates.

| Argument / option                   | Default                        | Description                                          |
| ----------------------------------- | ------------------------------ | ---------------------------------------------------- |
| `OLD_SYMBOL` (positional, required) | —                              | Current symbol name in the index (case-insensitive). |
| `NEW_SYMBOL` (positional, required) | —                              | Replacement symbol name (case-insensitive).          |
| `--data-dir`                        | `[zcrypto].data_dir` in toml   | Compiled qlib dataset directory.                     |
| `--backup-dir`                      | `[zcrypto].backup_dir` in toml | Backup dir (raw/ + snapshots/); created if absent.   |
| `--dry-run`                         | off                            | Print the rename plan and exit without writing.      |

```bash
zcrypto data rename MATICUSDT POLUSDT                                       # dirs from zcrypto.toml
zcrypto data rename MATICUSDT POLUSDT --backup-dir ./bk --data-dir ./data   # explicit overrides
zcrypto data rename MATICUSDT POLUSDT --dry-run                             # preview only
```

##### `zcrypto data aggtrades PAIRS_FILE`

Fetch a bounded daily aggTrades sample from `data.binance.vision` into the raw mirror. Purpose: execution-calibration research (tick-level fill/slippage analysis), **not** the Qlib kline dataset. Only touches the mirror under `--backup-dir`; no `index.json`, no compiled dataset, no qlib bins.

**Mirror layout:** zips are stored under a year subdir, mirroring the kline convention — e.g. `<backup-dir>/raw/spot/daily/aggTrades/BTCUSDT/2025/BTCUSDT-aggTrades-2025-03-01.zip`. The fetch is idempotent: a zip already present in the mirror is skipped (counted as "skipped" in the manifest), so re-running the same window costs nothing.

**Integrity gate:** a zip with a published `.CHECKSUM` is verified by sha256; one without is verified structurally (`validate_aggtrades_zip` — extracts to exactly one non-empty CSV) before being saved. An invalid zip is never cached.

**Manifest:** after the fetch completes, `aggtrades-manifest.json` is written to `<backup-dir>/raw/spot/daily/aggTrades/`, recording the pairs list, the `[from, to]` window, and per-pair **present** dates + total bytes — the cumulative sample on disk, so re-running the same window yields an identical manifest (idempotent), documenting what's available to the calibration.

| Argument / option                   | Default                        | Description                                                                                                   |
| ----------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| `PAIRS_FILE` (positional, required) | —                              | Plain text — one Binance symbol per line (blank lines allowed; symbols normalized to uppercase; ≥1 required). |
| `--backup-dir`                      | `[zcrypto].backup_dir` in toml | Backup dir where the raw mirror (`raw/`) lives; created if absent.                                            |
| `--from`                            | 7 days ago (UTC)               | Sample window start (ISO `YYYY-MM-DD`).                                                                       |
| `--to`                              | yesterday (UTC)                | Sample window end (ISO `YYYY-MM-DD`).                                                                         |
| `--dry-run`                         | off                            | Print the fetch plan (pairs × date count) and exit without fetching.                                          |

```bash
zcrypto data aggtrades pairs.txt --from 2025-03-01 --to 2025-03-07   # backup-dir from zcrypto.toml
zcrypto data aggtrades pairs.txt --backup-dir ./bk --from 2025-03-01 --to 2025-03-07
zcrypto data aggtrades pairs.txt --from 2025-03-01 --to 2025-03-07 --dry-run  # preview only
```

#### `zcrypto experiment`<a name="zcrypto-experiment"></a>

Run an end-to-end Qlib pipeline — Alpha158 features (158-factor library, default 2-day-forward label) → LightGBM ranker → TopkDropout long/cash daily backtest → 3- or 4-panel Plotly report — and write a predict-ready run bundle. The **recipe is the single swappable moving part**: swap `cli/experiment/recipes/<name>.py` to change the universe, features, model, strategy class, or strategy parameters and iterate.

> **Prerequisite:** Redis must be running before you invoke this command (`./scripts/redis.sh start`). The command performs a Redis pre-flight check and exits with a clear error if Redis is unreachable.

```bash
zcrypto experiment [--recipe skeleton] [--data-dir ./data] [--out ./runs] [--svg] [--refresh-cache] [--quick] [--open/--no-open] [--pit-universe]
```

By default `experiment` runs combinatorial purged cross-validation (CPCV) over `train+valid` — writing `cv_results.json` (per-path Sharpe distribution + rank-IC + holdout PSR) and a 4th report panel — then the single holdout backtest on `test`. `--quick` skips CPCV. Every run also writes `returns.csv` (holdout cost-adjusted daily returns) and prints a **holdout PSR** (Probabilistic Sharpe Ratio) line — P(true holdout Sharpe > 0), corrected for sample length and non-normality.

| Option                               | Default                      | Description                                                                                                                                                    |
| ------------------------------------ | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--recipe`                           | `skeleton`                   | Recipe name to run (see `cli/experiment/recipes/`).                                                                                                            |
| `--data-dir`                         | `[zcrypto].data_dir` in toml | Qlib provider directory (the `index.json` / `features/` / `calendars/` tree).                                                                                  |
| `--out`                              | `./runs`                     | Root directory for run bundles; each bundle lands at `<out>/<recipe>/<UTC timestamp>/`.                                                                        |
| `--svg/--no-svg`                     | off                          | Also render `report.svg` (requires kaleido).                                                                                                                   |
| `--refresh-cache`                    | off                          | Force-wipe qlib's on-disk feature/dataset cache before the run.                                                                                                |
| `--quick/--no-quick`                 | off                          | Skip CPCV; run only the single train→backtest holdout.                                                                                                         |
| `--open/--no-open`                   | on when stdout is a TTY      | Open `report.html` in a browser when done. Auto-detected from whether stdout is a TTY.                                                                         |
| `--seeds N`                          | `1`                          | Run the holdout N times with seeds 1…N and write `holdout_seeds.json` (per-seed metrics + distribution summary). No-op when `N=1` (default).                   |
| `--deterministic/--no-deterministic` | off                          | Fully deterministic mode: fixes seed=1 + LightGBM `force_row_wise`. Makes repeated runs byte-identical. Combine with `--seeds` for a canonical multi-seed run. |
| `--pit-universe/--no-pit-universe`   | off                          | Expand the recipe's universe to point-in-time membership (the ever-top-25 delisted/faded majors) for a survivorship-free run.                                  |
| `--fees-only/--no-fees-only`         | off                          | Use the fees-only cost model (no slippage/maker-fill) instead of the default calibrated realistic costs — the A/B baseline.                                    |

The **default cost model is calibrated realistic costs**: size-scaled slippage + maker-fill haircut derived from backtest calibration (see `cli/experiment/costs.py`). Pass `--fees-only` to revert to the raw `fee_preset` only (no slippage, no maker-fill haircut) for an A/B comparison.

##### Built-in recipes

| Recipe                        | Description                                                                                                                                                                                             |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `skeleton`                    | Naive baseline: `TopkDropoutStrategy` (topk=5), Alpha158 2-day label, no regime filter. Benchmark only — not a profitable strategy.                                                                     |
| `steady`                      | Low-turnover book: `TopkDropoutStrategy` (topk=10, hold_thresh=5), 5-day label, stronger regularization. Validated but beats neither steady market.                                                     |
| `linear_steady`               | `steady`'s book with a regularized linear model (Ridge, alpha=10) instead of LGBM (iter-27 model-axis test).                                                                                            |
| `h1_steady`                   | `steady`'s book with a 1-day label (iter-28 label-horizon sweep).                                                                                                                                       |
| `h10_steady`                  | `steady`'s book with a 10-day label (iter-28 label-horizon sweep).                                                                                                                                      |
| `h20_steady`                  | `steady`'s book with a 20-day label (iter-28 label-horizon sweep).                                                                                                                                      |
| `regime_steady`               | `steady`'s model + book with a BTC-trend regime overlay (`RegimeGatedTopkStrategy`, binary 200-day SMA, vol-targeting off) and walk-forward holdout.                                                    |
| `regime_fast`                 | `steady`'s book + a faster binary 100-day-MA BTC-trend regime gate (iter-23 responsiveness sweep).                                                                                                      |
| `regime_cross`                | `steady`'s book + a 50/200-day SMA golden-cross BTC-trend regime gate (iter-23 responsiveness sweep).                                                                                                   |
| `regime_graded`               | `steady`'s book + a graded 200-day-MA BTC-trend regime gate (partial exposure in a ±5% chop band; iter-24 refinement).                                                                                  |
| `regime_voltarget`            | `steady`'s book + a binary 200-day-MA gate with vol-targeting (exposure trimmed when BTC vol > 0.50; iter-24 refinement).                                                                               |
| `regime_equalweight`          | No-selection baseline: hold the whole universe equal-weight (constant signal + topk=19) under the same regime gate as regime_voltarget (iter-29 selection-value test).                                  |
| `regime_equalweight_majors`   | Gated equal-weight on the 10 large-cap majors (iter-30 universe A/B vs the broad regime_equalweight).                                                                                                   |
| `regime_equalweight_top5`     | Gated equal-weight on the 5 mega-caps (iter-31 concentration A/B vs regime_equalweight_majors).                                                                                                         |
| `regime_volweight_majors`     | Inverse-vol (risk-parity-lite) gated basket of the 10 majors (iter-32 A/B vs equal-weight).                                                                                                             |
| `alpha360_steady`             | `steady`'s book + qlib's built-in `Alpha360` feature handler (~360 raw OHLCV factors) instead of Alpha158. A/B against `steady`.                                                                        |
| `crossasset_steady`           | `steady`'s book + Alpha158 features + `CrossAssetProcessor`: BTC-anchored cross-asset features (relative strength, rolling beta, lead-lag, cointegration-deviation, cross-sectional momentum/vol rank). |
| `funding_steady`              | `steady`'s book + perp-funding carry features (`FundingRateProcessor`): level, z-score, cross-sectional rank, moving average, rate-of-change. Isolation A/B vs `steady`.                                |
| `regime_funding_voltarget`    | `funding_steady`'s book + a binary 200-day-MA regime gate with vol-targeting (iter-25 regime×funding stack test).                                                                                       |
| `regime_crossasset_voltarget` | `crossasset_steady`'s book + a binary 200-day-MA regime gate with vol-targeting (iter-26 regime×cross-asset stack test).                                                                                |
| `funding_crossasset_steady`   | `crossasset_steady`'s book + funding features stacked (`CrossAssetProcessor` then `FundingRateProcessor`). Stacking A/B vs `crossasset_steady`.                                                         |

##### Recipe fields: `feature_config`, `strategy_config`, and walk-forward knobs

Each recipe is a Python dataclass. Three sets of fields control the feature handler, the strategy class, and holdout retraining:

**`feature_config`** — selects the qlib feature handler class. Defaults to `Alpha158`; override to use `Alpha360` or a custom handler.

```python
feature_config = {
    "class": "Alpha158",
    "module_path": "qlib.contrib.data.handler",
}
```

The scaffold assembles the full handler config (instruments, segments, processors, label) from this dict; only the `class` and `module_path` vary across recipes.

**`strategy_config`** — a full strategy init dict (mirrors `model_config`) that the scaffold passes to `init_instance_by_config`. This makes the strategy class recipe-selectable; the runtime `signal=(model, dataset)` is injected automatically.

```python
strategy_config = {
    "class": "RegimeGatedTopkStrategy",
    "module_path": "cli.experiment.strategies.regime",
    "kwargs": {
        "topk": 10,
        "n_drop": 2,
        "hold_thresh": 5,
        "regime_mode": "binary",       # "binary" | "graded" | "cross"
        "regime_benchmark": "BTCUSDT",
        "regime_ma_window": 200,       # primary SMA window (days)
        "regime_ma_fast": None,        # fast SMA for "cross" mode
        "regime_band": 0.0,            # ±band around SMA for "graded" mode
        "chop_exposure": 0.5,          # exposure in the graded middle tier
        "vol_target": None,            # annualized vol target (None = off)
        "vol_lookback": 30,            # realized-vol lookback (days)
    },
}
```

`skeleton` and `steady` use `strategy_config` pointing at `TopkDropoutStrategy` — behavior-identical to before the seam was opened.

**Walk-forward knobs** (holdout only; CPCV is unaffected):

| Field              | Default       | Description                                                                         |
| ------------------ | ------------- | ----------------------------------------------------------------------------------- |
| `wf_enabled`       | `False`       | Enable walk-forward holdout retraining (off by default; `regime_steady` sets True). |
| `wf_retrain_freq`  | `"quarter"`   | Retrain cadence: `"quarter"` or `"year"`.                                           |
| `wf_window`        | `"expanding"` | Window type: `"expanding"` (all history to period start) or `"rolling"`.            |
| `wf_rolling_years` | `3`           | Training window length when `wf_window="rolling"` (years).                          |

When `wf_enabled=True`, the holdout is produced by looping retrain periods: fit on the train window, predict the period, backtest it, then stitch the per-period daily returns into one holdout curve. The stitched curve feeds the same `metrics.json` / `returns.csv` / holdout PSR outputs as the single-fit path. Each period starts all-cash (conservative; mirrors CPCV path independence).

**Run bundle layout** — each run writes a timestamped directory `runs/<recipe>/<UTC-timestamp>/`:

| File                   | Description                                                                                                                                                                    |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `report.html`          | 3- or 4-panel Plotly report: equity vs BTCUSDT buy-and-hold / trade timeline / full-history context / CPCV OOS Sharpe distribution (descriptive; 4th panel, default only).     |
| `report.svg`           | Static SVG export of the same report (only with `--svg`).                                                                                                                      |
| `metrics.json`         | Annualized return, max drawdown, information ratio and other backtest metrics.                                                                                                 |
| `cv_results.json`      | CPCV out-of-sample results: per-path Sharpe/return/drawdown, Sharpe distribution stats, rank-IC, and holdout summary including `psr` (written by default, not with `--quick`). |
| `returns.csv`          | Holdout cost-adjusted daily returns (`date,ret`); consumed by `zcrypto rank`.                                                                                                  |
| `trades.csv`           | Flat trade log (one row per executed order).                                                                                                                                   |
| `run_meta.json`        | Manifest: recipe, git commit, qlib/lightgbm versions, segments, universe, fee preset, index fingerprint.                                                                       |
| `recipe_snapshot.json` | Full recipe parameters as a JSON dict (reproducibility).                                                                                                                       |
| `holdout_seeds.json`   | Per-seed holdout metrics + distribution summary (only with `--seeds N` where N>1): `{"per_seed": [{seed, ending_value, sharpe, psr, max_drawdown}, …], "summary": {…}}`.       |
| `model.pkl`            | Predict-ready serialized LightGBM model (copied from the per-run MLflow store).                                                                                                |
| `mlruns/`              | Per-run MLflow experiment store; inspect with `mlflow ui --backend-store-uri runs/<recipe>/<ts>/mlruns`.                                                                       |

> **Realistic-expectations caveat:** The default `skeleton` recipe is a naive baseline, **not** a profitable strategy. A cold run over the 2025–2026 test window currently turns 10,000 → ~3,700 USDT and underperforms BTCUSDT buy-and-hold. It exists to validate the pipeline and to be iterated on — see `docs/open-topics/` for the deferred robustness topics (validation rigor, regime overlay, realistic execution, point-in-time universe, paper trading).

Every run emits a survivorship caveat (universe is today's surviving pairs; delisted pairs absent) — shown in the report title and stdout, and recorded under `caveats` in `run_meta.json`; see open-topic `T0005`.

```bash
./scripts/redis.sh start                                      # ensure Redis is up
zcrypto experiment                                            # run with CPCV + holdout (default)
zcrypto experiment --quick                                    # holdout only; skip CPCV
zcrypto experiment --recipe regime_steady                     # BTC-regime overlay + walk-forward
zcrypto experiment --recipe my_recipe                         # run a custom recipe
zcrypto experiment --refresh-cache --no-open                  # bust the cache; no browser
zcrypto experiment --deterministic                            # reproducible canonical run (seed=1)
zcrypto experiment --seeds 20 --deterministic                 # canonical run + 20-seed holdout distribution → holdout_seeds.json
mlflow ui --backend-store-uri runs/skeleton/<ts>/mlruns       # inspect the MLflow run
```

#### `zcrypto rank`<a name="zcrypto-rank"></a>

Scan all run bundles under `--out` as trials and report the **deflated Sharpe ratio** (DSR) of the best trial and the **probability of backtest overfitting** (PBO via CSCV). Produces a ranked table and writes `runs/rank.json`.

DSR applies an N-trials correction to the best-trial Sharpe — it reports P(the best trial's true Sharpe exceeds what N random trials would achieve by luck). PBO (CSCV) estimates the probability that an in-sample-best strategy underperforms the median out-of-sample. Together they give an honest read on whether the best run is genuinely better or merely lucky selection bias.

```bash
zcrypto rank [--out ./runs] [--n-splits 16]
```

| Option       | Default  | Description                                                                           |
| ------------ | -------- | ------------------------------------------------------------------------------------- |
| `--out`      | `./runs` | Run-bundle root to scan for trials (searches `<out>/<recipe>/<run>/returns.csv`).     |
| `--n-splits` | `16`     | Number of CSCV splits for PBO (must be even; more splits → finer logit distribution). |

The command writes `<out>/rank.json` with keys `n_trials`, `window` (common date range), `n_splits`, `trials` (per-trial `recipe`, `run`, `sharpe_daily`, `psr`), `dsr_best`, and `pbo`. The `sharpe_daily` column (also labelled `Sharpe(d)` in the ranked table) is the **per-period (daily) Sharpe** of each trial's holdout returns — distinct from `experiment`'s annualized holdout Sharpe in `cv_results.json`; DSR/PBO/PSR are all computed on these per-period values. DSR and PBO are `NaN` when fewer than 2 trials exist.

```bash
zcrypto rank                          # scan runs/ from cwd
zcrypto rank --out ./runs             # explicit output dir
zcrypto rank --n-splits 8             # fewer splits (faster, coarser PBO estimate)
```

#### `zcrypto stress`<a name="zcrypto-stress"></a>

Walk-forward out-of-sample validation: loops over annual OOS windows (2022, 2023, 2024, 2025), trains only on data strictly before each test period (expanding from data start), and runs the multi-seed holdout per window to report per-window long-only and market-neutral L/S Sharpe. The test windows are fixed (`2022-01-01`, `2023-01-01`, `2024-01-01`, `2025-01-01`); training data expands from `data_start` up to `test_start − 8 days` (purge gap). Writes `stress_summary.json` to the output bundle.

```bash
zcrypto stress [--recipe steady] [--seeds 8] [--data-dir ./data] [--out ./runs]
```

| Option       | Default    | Description                                                                           |
| ------------ | ---------- | ------------------------------------------------------------------------------------- |
| `--recipe`   | `steady`   | Recipe to validate out-of-sample (see `cli/experiment/recipes`).                      |
| `--seeds`    | `8`        | Seeds per OOS window; reuses the multi-seed holdout (`run_holdout_seeds`) per window. |
| `--data-dir` | _(config)_ | Qlib provider directory. Defaults to `[zcrypto].data_dir` in `zcrypto.toml`.          |
| `--out`      | `./runs`   | Root for stress bundles; each run lands at `<out>/stress/<recipe>/<UTC timestamp>/`.  |

The command writes `<out>/stress/<recipe>/<ts>/stress_summary.json` with keys `recipe`, `seeds`, `windows` (per-window `label`, `train`, `test`, `sharpe_mean`, `ls_sharpe_mean`, `ls_sharpe_min`), and `aggregate` (cross-window L/S Sharpe summary).
