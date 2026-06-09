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

| Command   | Description                                              |
| --------- | -------------------------------------------------------- |
| `example` | Run a small offline Qlib ETH-USD strategy backtest demo. |
| `data`    | Manage the Binance → Qlib dataset (download / verify).   |

```bash
zcrypto example                # run the demo backtest
zcrypto example --show-data    # also print the prepared feature-frame head
```

#### `zcrypto data`

Prepare a Qlib-ready dataset from Binance spot klines. Bare `zcrypto data` prints this group's help and exits.

##### `zcrypto data download OUT_DIR PAIRS_FILE`

Fetch Binance spot 1d klines from `data.binance.vision`, sha256-validate them, and write/append a Qlib-ready dataset to `OUT_DIR`.

| Argument / option                   | Default         | Description                                                                                                                   |
| ----------------------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `OUT_DIR` (positional, required)    | —               | Dataset directory; created if absent.                                                                                         |
| `PAIRS_FILE` (positional, required) | —               | Plain text — one Binance symbol per line (blank lines allowed; symbols are case-normalized to uppercase; ≥1 symbol required). |
| `--interval`                        | `1d`            | Kline interval. Only `1d` is supported in iter-4.                                                                             |
| `--from`                            | `2020-01-01`    | Lower bound (ISO `YYYY-MM-DD`).                                                                                               |
| `--to`                              | yesterday (UTC) | Upper bound (ISO `YYYY-MM-DD`).                                                                                               |

```bash
echo BTCUSDT > pairs.txt
zcrypto data download ./ds pairs.txt --from 2024-01-01 --to 2024-01-31
```

**Concurrency:** `data download` fetches up to **5** daily zips in parallel (gentle by default to avoid hammering the data archive). The cap is set by `CliConstants.FETCH_CONCURRENCY` in `cli/constants.py`; tune by editing the constant — there is no env var or CLI flag for this. The convention is that low-change operational config lives in `CliConstants`; high-change-odds config gets a Typer flag.

##### `zcrypto data verify OUT_DIR`

Re-validate an existing dataset against `index.json` and all invariants. Read-only.

| Option     | Description                                                                      |
| ---------- | -------------------------------------------------------------------------------- |
| `--silent` | Print nothing; convey result via exit code only (0 = valid, non-zero = problem). |

```bash
zcrypto data verify ./ds
```
