![Version](https://img.shields.io/badge/version-v0.1.1-blue)
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

##### `zcrypto data download OUT_DIR PAIRS_FILE`

Fetch Binance spot 1d klines from `data.binance.vision`, sha256-validate them, and write/append a Qlib-ready dataset to `OUT_DIR`.

| Argument / option                   | Default         | Description                                                                                                                   |
| ----------------------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `OUT_DIR` (positional, required)    | —               | Dataset directory; created if absent.                                                                                         |
| `PAIRS_FILE` (positional, required) | —               | Plain text — one Binance symbol per line (blank lines allowed; symbols are case-normalized to uppercase; ≥1 symbol required). |
| `--interval`                        | `1d`            | Kline interval. Only `1d` is supported in iter-5.                                                                             |
| `--from`                            | `2020-01-01`    | Lower bound (ISO `YYYY-MM-DD`).                                                                                               |
| `--to`                              | yesterday (UTC) | Upper bound (ISO `YYYY-MM-DD`).                                                                                               |
| `--dry-run`                         | off             | Print the fetch plan and exit without writing anything.                                                                       |

```bash
echo BTCUSDT > pairs.txt
zcrypto data download ./ds pairs.txt --from 2024-01-01 --to 2024-01-31
zcrypto data download ./ds pairs.txt --dry-run          # preview only
```

**Concurrency:** `data download` fetches up to **8** daily zips in parallel (gentle by default to avoid hammering the data archive). The cap is set by `CliConstants.FETCH_CONCURRENCY` in `cli/constants.py`; tune by editing the constant — there is no env var or CLI flag for this. The convention is that low-change operational config lives in `CliConstants`; high-change-odds config gets a Typer flag.

**Local mirror & recovery:** every verified zip is saved to a dataset-local mirror at `<OUT_DIR>/.raw`, under a tree that mirrors the remote archive layout plus a year subdir — e.g. `./ds/.raw/spot/daily/klines/DOTUSDT/1d/2025/DOTUSDT-1d-2025-10-14.zip`. On a later run a present zip is read from the mirror instead of re-downloaded, so a partial or failed download resumes cheaply rather than starting over. Like `.snapshots/` and `.staging/`, the `.raw/` directory lives inside `OUT_DIR` but is excluded from snapshots, verification, and the atomic commit. The mirror is trusted as immutable and read without re-checksumming; delete a file (or the tree) to force a re-fetch.

**Missing `.CHECKSUM`:** some recent archive days ship the zip without a sibling `.CHECKSUM`. Rather than fail, the download verifies the zip structurally (it extracts to exactly one parse-able CSV), logs a warning, and continues.

##### `zcrypto data verify OUT_DIR`

Re-validate an existing dataset against `index.json` and all invariants. Read-only. Unless `--silent`, it prints a checklist of exactly what was validated (schema, calendar density + sha256, instruments, per-pair bin sha256/size/header and `rows`/`to` cross-checks, orphan scan).

Two dataset-level scans run here:

- **Interior-gap check (fails):** every calendar day between the dataset's first and last day must be covered by at least one pair. A stretch covered by no pair (e.g. two pairs with a listing gap between them that was never bridged by `rename`) is reported and exits non-zero. (This completeness check is specific to the command; the internal post-mutation gate accepts such structurally-valid intermediate states.)
- **Synthetic-day report (informational):** days carrying `NaN` prices — the suspension bars a `rename` writes to bridge a delist→relist gap — are listed per pair. Not a failure.

| Option     | Description                                                                      |
| ---------- | -------------------------------------------------------------------------------- |
| `--silent` | Print nothing; convey result via exit code only (0 = valid, non-zero = problem). |

```bash
zcrypto data verify ./ds
```

##### `zcrypto data backfill OUT_DIR`

Extend every `TRADING` pair in the dataset forward to `--to` (default yesterday UTC). Non-`TRADING` pairs (delisted, halted) are silently skipped. The command is a no-op when all pairs are already caught up or all are non-`TRADING`; in that case no snapshot is written.

| Argument / option                | Default         | Description                                                 |
| -------------------------------- | --------------- | ----------------------------------------------------------- |
| `OUT_DIR` (positional, required) | —               | Dataset directory (must already contain a seeded dataset).  |
| `--to`                           | yesterday (UTC) | Extend up to this date (ISO `YYYY-MM-DD`).                  |
| `--dry-run`                      | off             | Print the per-pair extension plan and exit without writing. |

```bash
zcrypto data backfill ./ds                        # extend to yesterday
zcrypto data backfill ./ds --to 2024-06-30        # extend to a specific date
zcrypto data backfill ./ds --dry-run              # preview only
```

##### `zcrypto data delist OUT_DIR SYMBOL`

Remove a pair from the dataset. The calendar is conditionally shrunk: if the delisted pair was the earliest or latest in the dataset the calendar is front- or back-trimmed to cover the remaining pairs; a mid-calendar delist that would leave a gap is rejected with an error.

Refuses with an actionable error when: the symbol is not in the index, it is the last pair in the dataset, or removing it would create a non-contiguous calendar gap.

| Argument / option                | Default | Description                                     |
| -------------------------------- | ------- | ----------------------------------------------- |
| `OUT_DIR` (positional, required) | —       | Dataset directory.                              |
| `SYMBOL` (positional, required)  | —       | Binance symbol to remove (case-insensitive).    |
| `--dry-run`                      | off     | Print the delist plan and exit without writing. |

```bash
zcrypto data delist ./ds MATICUSDT
zcrypto data delist ./ds MATICUSDT --dry-run      # preview only
```

##### `zcrypto data rename OUT_DIR OLD_SYMBOL NEW_SYMBOL`

Relabel a pair. Two variants are detected automatically from the index:

- **Variant 1** — `OLD_SYMBOL` is in the index but `NEW_SYMBOL` is not. The command probes `data.binance.vision` for `NEW_SYMBOL`'s first available archive day, synthesizes any gap between `OLD_SYMBOL`'s last day and that first day as suspension bars (OHLC/VWAP = `NaN`, volume/amount/trades = `0`, `factor = 1.0`), and relabels the dataset entry. The renamed pair's `dates_to` is set to `new_first - 1 day`. `NaN` is qlib's native "suspended / not tradable" marker — its backtest treats those days as untradable, so the gap drops out of returns and indicators instead of injecting fake flat bars.
- **Variant 2** — both `OLD_SYMBOL` and `NEW_SYMBOL` are in the index (e.g. both were downloaded by `data download`). `OLD_SYMBOL`'s historical bins are prepended to `NEW_SYMBOL`'s bins with the same synthetic suspension gap fill in between. `OLD_SYMBOL` is then removed from the index.

Refuses with an error when: `OLD_SYMBOL` is not in the index, `OLD_SYMBOL` equals `NEW_SYMBOL`, `NEW_SYMBOL` is not a valid Binance symbol (exchangeInfo), or (Variant 2) the two ranges overlap.

**Operational precondition.** Run `data backfill` immediately before `data rename` so `OLD_SYMBOL`'s `index.to` reflects its last real trading day. If `index.to` is stale, the synthetic gap fill will silently cover dates when `OLD_SYMBOL` was actually trading — distorting analysis for those dates.

| Argument / option                   | Default | Description                                          |
| ----------------------------------- | ------- | ---------------------------------------------------- |
| `OUT_DIR` (positional, required)    | —       | Dataset directory.                                   |
| `OLD_SYMBOL` (positional, required) | —       | Current symbol name in the index (case-insensitive). |
| `NEW_SYMBOL` (positional, required) | —       | Replacement symbol name (case-insensitive).          |
| `--dry-run`                         | off     | Print the rename plan and exit without writing.      |

```bash
zcrypto data rename ./ds MATICUSDT POLUSDT
zcrypto data rename ./ds MATICUSDT POLUSDT --dry-run   # preview only
```
