![Version](https://img.shields.io/badge/version-v0.0.0-blue)
![GitHub License](https://img.shields.io/github/license/zhaow-de/zcrypto)
![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https://raw.githubusercontent.com/zhaow-de/zcrypto/develop/pyproject.toml)
![Coveralls](https://img.shields.io/coverallsCoverage/github/zhaow-de/zcrypto)

# zcrypto

Learning-for-Fun project to experience Microsoft Qlib.

<!-- mdformat-toc start --slug=github --maxlevel=3 --minlevel=2 -->

- [Requirements](#requirements)
- [Usage](#usage)

<!-- mdformat-toc end -->

## Requirements<a name="requirements"></a>

`zcrypto` runs Qlib workflows (e.g. `zcrypto example`), which import LightGBM and therefore need the OpenMP runtime installed on your system:

- **macOS:** `brew install libomp`
- **Debian/Ubuntu:** `sudo apt-get install libgomp1`

## Usage<a name="usage"></a>

```bash
zcrypto [OPTIONS]          # or: uv run python -m cli [OPTIONS]
```

| Option            | Description                            |
| ----------------- | -------------------------------------- |
| `-v`, `--version` | Show the application version and exit. |
| `-h`, `--help`    | Show help and exit.                    |

Running with no options prints the help.
