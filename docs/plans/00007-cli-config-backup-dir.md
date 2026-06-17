# App-level `zcrypto.toml` config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize the CLI's configuration in a committed `zcrypto.toml`: the two dataset directories resolve **flag → config → error**, and the seven `CliConstants` operational knobs move into a `[zcrypto.fetch]` table that **overrides built-in defaults**, injected via a `FetchConfig` dataclass.

**Architecture:** A new framework-agnostic `cli/config.py` (stdlib `tomllib`) exposes `AppConfig`/`FetchConfig`/`ConfigError`, `load_config()`, and `resolve_data_dir`/`resolve_backup_dir`. Paths have no built-in default (unresolved → `ConfigError` → stderr + non-zero exit). The seven operational settings become `FetchConfig` fields (defaults == today's `CliConstants` values); `CliConstants` is deleted and `FetchConfig` is dependency-injected from the command layer into `download`/`backfill`/`rename` pipelines and `BinanceSource`. The three pipeline entry points and `BinanceSource` take `fetch: FetchConfig = FetchConfig()` (a defaulted keyword arg, so the ~77 existing direct-call test sites are untouched; the command layer always passes `cfg.fetch` explicitly).

**Tech Stack:** Python 3.12 (`tomllib` stdlib), Typer, pytest, uv, ruff (line length 132).

**Spec:** `docs/specs/00007-cli-config-backup-dir-design.md`

---

## File structure

- **Create** `cli/config.py` — `ConfigError`, `FetchConfig`, `AppConfig`, `load_config`, `resolve_data_dir`, `resolve_backup_dir`.
- **Create** `zcrypto.toml` — committed config (`[zcrypto]` paths + `[zcrypto.fetch]` tuning).
- **Create** `tests/test_config.py` — loader + resolver unit tests.
- **Modify** `cli/data/binance.py` — `BinanceSource(fetch=…)`, `_retryable_request(attempts: int)`; drop `CliConstants`.
- **Modify** `cli/data/pipeline.py` — `fetch` param threaded into `download`/`backfill`/`rename` pipelines + helpers; drop `CliConstants`.
- **Delete** `cli/constants.py`, `tests/test_constants.py`.
- **Modify** `cli/data/command.py` — positional `BACKUP_DIR` → `--backup-dir`; `--data-dir` → config-resolved; inject `cfg.fetch`.
- **Modify** `cli/experiment/command.py` — `--data-dir` → config-resolved.
- **Modify** tests: `tests/test_data_pipeline.py`, `tests/test_data_command.py`, `tests/test_experiment_command.py`.
- **Modify** `README.md`, `docs/iterations-history.md`.

Common commit footer (added by the implementer per `.claude/rules/commit-messages.md`): a `Co-Authored-By:` trailer naming the actual implementing model, e.g. `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`. Run `uv run ruff check --fix && uv run ruff format` before each commit; never `--no-verify`.

---

## Task 1: Config loader (`cli/config.py`)

**Files:**
- Create: `cli/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_config.py`:

```python
from pathlib import Path

import pytest

from cli.config import (
    AppConfig,
    ConfigError,
    FetchConfig,
    load_config,
    resolve_backup_dir,
    resolve_data_dir,
)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "zcrypto.toml"
    p.write_text(body)
    return p


def test_absent_file_yields_none_paths_and_default_fetch(tmp_path):
    cfg = load_config(tmp_path / "zcrypto.toml")
    assert cfg.data_dir is None
    assert cfg.backup_dir is None
    assert cfg.fetch == FetchConfig()


def test_reads_paths(tmp_path):
    cfg = load_config(_write(tmp_path, '[zcrypto]\ndata_dir = "data"\nbackup_dir = "../zcrypto-data"\n'))
    assert cfg.data_dir == Path("data")
    assert cfg.backup_dir == Path("../zcrypto-data")


def test_missing_one_path_key_is_none(tmp_path):
    cfg = load_config(_write(tmp_path, '[zcrypto]\ndata_dir = "data"\n'))
    assert cfg.data_dir == Path("data")
    assert cfg.backup_dir is None


def test_fetch_override_merges_over_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, "[zcrypto.fetch]\nfetch_concurrency = 3\n"))
    assert cfg.fetch.fetch_concurrency == 3
    assert cfg.fetch.http_timeout_get_secs == 60  # untouched default


def test_malformed_toml_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "this is = = not toml"))


def test_non_string_path_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "[zcrypto]\ndata_dir = 5\n"))


def test_non_positive_fetch_value_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "[zcrypto.fetch]\nfetch_concurrency = 0\n"))


def test_non_int_fetch_value_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, '[zcrypto.fetch]\nfetch_concurrency = "x"\n'))


def test_unknown_fetch_key_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "[zcrypto.fetch]\nnope = 1\n"))


def test_resolve_flag_wins(tmp_path):
    cfg = load_config(_write(tmp_path, '[zcrypto]\ndata_dir = "from_config"\n'))
    assert resolve_data_dir(Path("from_flag"), cfg) == Path("from_flag")


def test_resolve_falls_back_to_config(tmp_path):
    cfg = load_config(_write(tmp_path, '[zcrypto]\nbackup_dir = "cfg_bk"\n'))
    assert resolve_backup_dir(None, cfg) == Path("cfg_bk")


def test_resolve_unconfigured_raises_with_both_remedies():
    cfg = AppConfig(data_dir=None, backup_dir=None, fetch=FetchConfig())
    with pytest.raises(ConfigError) as exc:
        resolve_data_dir(None, cfg)
    msg = str(exc.value)
    assert "--data-dir" in msg and "[zcrypto].data_dir" in msg
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'cli.config'`.

- [ ] **Step 3: Implement `cli/config.py`**

```python
from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

CONFIG_FILENAME = "zcrypto.toml"
CONFIG_TABLE = "zcrypto"


class ConfigError(Exception):
    """zcrypto.toml is malformed, or a required setting cannot be resolved."""


@dataclass(frozen=True)
class FetchConfig:
    """Operational tuning for `zcrypto data` fetching/pipelines. Each field overrides
    a built-in default via the [zcrypto.fetch] table in zcrypto.toml."""

    fetch_concurrency: int = 8
    http_timeout_head_secs: int = 5
    http_timeout_get_secs: int = 60
    http_retry_attempts: int = 3
    fetch_progress_log_interval: int = 50
    backfill_right_edge_grace_days: int = 7
    rename_synth_warn_days: int = 7


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path | None
    backup_dir: Path | None
    fetch: FetchConfig


def _read_path(table: dict, key: str, config_path: Path) -> Path | None:
    if key not in table:
        return None
    value = table[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"[{CONFIG_TABLE}].{key} in {config_path} must be a non-empty string")
    return Path(value)


def _build_fetch(table: dict, config_path: Path) -> FetchConfig:
    raw = table.get("fetch", {})
    if not isinstance(raw, dict):
        raise ConfigError(f"[{CONFIG_TABLE}.fetch] in {config_path} must be a table")
    known = {f.name for f in fields(FetchConfig)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"[{CONFIG_TABLE}.fetch] in {config_path} has unknown key(s): {', '.join(unknown)}")
    overrides: dict[str, int] = {}
    for name in known & set(raw):
        value = raw[name]
        # bool is a subclass of int — reject it explicitly.
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ConfigError(f"[{CONFIG_TABLE}.fetch].{name} in {config_path} must be a positive integer")
        overrides[name] = value
    return FetchConfig(**overrides)


def load_config(config_path: Path = Path(CONFIG_FILENAME)) -> AppConfig:
    if not config_path.exists():
        return AppConfig(data_dir=None, backup_dir=None, fetch=FetchConfig())
    try:
        raw = tomllib.loads(config_path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{config_path} is not valid TOML: {e}") from e
    table = raw.get(CONFIG_TABLE, {})
    if not isinstance(table, dict):
        raise ConfigError(f"[{CONFIG_TABLE}] in {config_path} must be a table")
    return AppConfig(
        data_dir=_read_path(table, "data_dir", config_path),
        backup_dir=_read_path(table, "backup_dir", config_path),
        fetch=_build_fetch(table, config_path),
    )


def _resolve(flag_value: Path | None, config_value: Path | None, *, name: str, flag: str) -> Path:
    if flag_value is not None:
        return flag_value
    if config_value is not None:
        return config_value
    raise ConfigError(f"no {name} configured — set [{CONFIG_TABLE}].{name} in {CONFIG_FILENAME} or pass {flag} <path>.")


def resolve_data_dir(flag_value: Path | None, cfg: AppConfig) -> Path:
    return _resolve(flag_value, cfg.data_dir, name="data_dir", flag="--data-dir")


def resolve_backup_dir(flag_value: Path | None, cfg: AppConfig) -> Path:
    return _resolve(flag_value, cfg.backup_dir, name="backup_dir", flag="--backup-dir")
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix && uv run ruff format
git add cli/config.py tests/test_config.py
git commit -m "feat(config): add zcrypto.toml loader (AppConfig/FetchConfig/resolvers)"
```

---

## Task 2: Committed `zcrypto.toml`

**Files:**
- Create: `zcrypto.toml`

- [ ] **Step 1: Create `zcrypto.toml`** at the repo root:

```toml
[zcrypto]
# Compiled qlib dataset dir (calendars/, instruments/, features/, index.json).
data_dir = "data"
# Durable backup root holding raw/ (downloaded-zip mirror) and snapshots/.
backup_dir = "../zcrypto-data"

# Operational tuning for `zcrypto data` fetching/pipelines. Each key overrides a
# built-in default; omit a key (or this whole table) to use the default shown.
[zcrypto.fetch]
fetch_concurrency = 8              # max parallel HTTP fetches in `data download`
http_timeout_head_secs = 5         # socket timeout for HEAD / small-body requests
http_timeout_get_secs = 60         # socket timeout for daily-zip GETs
http_retry_attempts = 3            # total attempts per HTTP call (transient failures)
fetch_progress_log_interval = 50   # emit a progress log every N completed (pair, date)
backfill_right_edge_grace_days = 7 # right-edge absence tolerated before delist/rename hint
rename_synth_warn_days = 7         # synthetic-gap-fill threshold for a louder rename warning
```

- [ ] **Step 2: Sanity-check it loads**

Run: `uv run python -c "from cli.config import load_config; print(load_config())"`
Expected: prints `AppConfig(data_dir=PosixPath('data'), backup_dir=PosixPath('../zcrypto-data'), fetch=FetchConfig(fetch_concurrency=8, ...))`.

- [ ] **Step 3: Commit**

```bash
git add zcrypto.toml
git commit -m "feat(config): add committed zcrypto.toml with dataset dirs + fetch tuning"
```

---

## Task 3: Inject `FetchConfig` into `BinanceSource` (`cli/data/binance.py`)

**Files:**
- Modify: `cli/data/binance.py`
- Test: `tests/test_data_binance.py` (verify still green; no edits expected)

- [ ] **Step 1: Replace the `CliConstants` import**

In `cli/data/binance.py`, replace line `from cli.constants import CliConstants` with:

```python
from cli.config import FetchConfig
```

- [ ] **Step 2: Make `_retryable_request` take an explicit `attempts: int`**

Change its signature/body (remove the `CliConstants` fallback):

```python
def _retryable_request(
    method: str,
    url: str,
    *,
    timeout: float,
    attempts: int,
    base_delay: float = 1.0,
):  # pragma: no cover
    """`_pool.request` with timeout + retry on transient failures.

    Retries on: urllib3 connection / timeout exceptions, 5xx responses.
    Raises HttpStatusError immediately on 4xx (a 404 is a meaningful signal —
    the pair-date doesn't exist). Exponential backoff: base_delay, *2, *4, ..."""
    last_exc = None
    for attempt in range(attempts):
        # ... body unchanged ...
```

(Delete the `if attempts is None: attempts = CliConstants.HTTP_RETRY_ATTEMPTS` lines and the `attempts: int | None = None` default. The rest of the body is unchanged.)

- [ ] **Step 3: Give `BinanceSource` a `fetch` and use it in every method**

```python
class BinanceSource:
    """Concrete `Source` over urllib3 PoolManager. HTTP paths excluded from coverage."""

    def __init__(self, fetch: FetchConfig = FetchConfig()):
        self._fetch = fetch

    def fetch_exchange_info(self) -> list[dict]:  # pragma: no cover
        resp = _retryable_request(
            "GET", EXCHANGE_INFO_URL, timeout=self._fetch.http_timeout_get_secs, attempts=self._fetch.http_retry_attempts
        )
        data = json.loads(resp.data)
        return data["symbols"]

    def exists_kline(self, symbol: str, interval: str, date: dt.date) -> bool:  # pragma: no cover
        url = kline_zip_url(symbol, interval, date)
        try:
            _retryable_request(
                "HEAD", url, timeout=self._fetch.http_timeout_head_secs, attempts=self._fetch.http_retry_attempts
            )
            return True
        except HttpStatusError as e:
            if e.status == 404:
                return False
            raise

    def fetch_kline_zip(self, symbol: str, interval: str, date: dt.date) -> bytes:  # pragma: no cover
        url = kline_zip_url(symbol, interval, date)
        resp = _retryable_request(
            "GET", url, timeout=self._fetch.http_timeout_get_secs, attempts=self._fetch.http_retry_attempts
        )
        return resp.data

    def fetch_kline_checksum(self, symbol: str, interval: str, date: dt.date) -> str | None:  # pragma: no cover
        """The published sha256 for this zip, or None if no `.CHECKSUM` exists (404)."""
        url = kline_checksum_url(symbol, interval, date)
        try:
            resp = _retryable_request(
                "GET", url, timeout=self._fetch.http_timeout_head_secs, attempts=self._fetch.http_retry_attempts
            )
        except HttpStatusError as e:
            if e.status == 404:
                return None
            raise
        return parse_checksum_file(resp.data.decode("utf-8"))
```

- [ ] **Step 4: Run binance tests**

Run: `uv run pytest tests/test_data_binance.py -q`
Expected: PASS (the `_retryable_request` tests already pass `attempts=3` explicitly; `from cli.config import FetchConfig` resolves; `CliConstants` no longer referenced here).

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix && uv run ruff format
git add cli/data/binance.py
git commit -m "refactor(data): inject FetchConfig into BinanceSource (drop CliConstants from binance)"
```

---

## Task 4: Thread `FetchConfig` through the pipelines (`cli/data/pipeline.py`)

**Files:**
- Modify: `cli/data/pipeline.py`
- Test: `tests/test_data_pipeline.py`

- [ ] **Step 1: Update the concurrency test first (TDD)**

In `tests/test_data_pipeline.py`, rewrite `test_download_fetches_concurrently_within_cap` to inject the cap instead of monkeypatching `CliConstants`:

```python
def test_download_fetches_concurrently_within_cap(tmp_path):
    """Peak concurrent fetches stays <= the injected fetch_concurrency AND parallelism actually happens."""
    from cli.config import FetchConfig

    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = CountingSource(request_delay=0.05)
    src.add_pair("BTCUSDT", "BTC", "USDT")
    for d in (dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(15)):
        src.add_kline("BTCUSDT", "1d", d)
    download_pipeline(
        paths,
        pairs,
        "1d",
        dt.date(2024, 1, 1),
        dt.date(2024, 1, 15),
        src,
        fetch=FetchConfig(fetch_concurrency=3),
    )
    assert src.peak_concurrent <= 3, f"expected peak <= 3, got {src.peak_concurrent}"
    assert src.peak_concurrent >= 2, f"expected concurrent fetches, peak was only {src.peak_concurrent}"
    assert src.total_requests == 15
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_data_pipeline.py::test_download_fetches_concurrently_within_cap -q`
Expected: FAIL — `download_pipeline() got an unexpected keyword argument 'fetch'`.

- [ ] **Step 3: Edit `cli/data/pipeline.py` — imports**

Replace `from cli.constants import CliConstants` with:

```python
from cli.config import FetchConfig
```

- [ ] **Step 4: Thread `fetch` into the download path**

- `_resolve_ranges(...)`: add a trailing parameter `fetch: FetchConfig`. Replace both occurrences of `CliConstants.BACKFILL_RIGHT_EDGE_GRACE_DAYS` (in the `days_since > …` check and the error message) with `fetch.backfill_right_edge_grace_days`.
- `_download_plan(out_dir, pairs_file, interval, from_date, to_date, source)`: add a trailing `fetch: FetchConfig`; forward it in its `_resolve_ranges(pair_to_assets, existing, source, interval, arg_from, arg_to, fetch)` call.
- `_fetch_all_concurrent(source, plan, interval, max_workers, mirror_root)`: change the signature to `(source, plan, interval, fetch: FetchConfig, mirror_root)`; at the top of the body add `max_workers = fetch.fetch_concurrency`, and replace `log_every = CliConstants.FETCH_PROGRESS_LOG_INTERVAL` with `log_every = fetch.fetch_progress_log_interval`. (The internal references to `max_workers` stay.)
- `_download_apply(paths, staging, plan, source)`: add a trailing `fetch: FetchConfig`; change its `_fetch_all_concurrent(source, non_empty, plan.interval, CliConstants.FETCH_CONCURRENCY, mirror.root_for(paths))` call to `_fetch_all_concurrent(source, non_empty, plan.interval, fetch, mirror.root_for(paths))`.
- `download_pipeline(...)`: add `fetch: FetchConfig = FetchConfig()` as the first keyword-only arg (right after the `*,`), and update the closures:

```python
def download_pipeline(
    paths: DatasetPaths,
    pairs_file: Path,
    interval: str,
    from_date: dt.date,
    to_date: dt.date,
    source: Source,
    *,
    fetch: FetchConfig = FetchConfig(),
    dry_run: bool = False,
) -> None:
    """Orchestrate: parse → validate → resolve → fetch → stage → verify → commit."""
    plan_fn = lambda d: _download_plan(d, pairs_file, interval, from_date, to_date, source, fetch)
    apply_fn = lambda paths, s, p: _download_apply(paths, s, p, source, fetch)
    _execute_mutation(paths, "download", plan_fn, apply_fn, dry_run=dry_run)
```

- [ ] **Step 5: Thread `fetch` into the backfill path**

- `_backfill_plan(out_dir, interval, arg_to, source)`: add a trailing `fetch: FetchConfig`; replace both `CliConstants.BACKFILL_RIGHT_EDGE_GRACE_DAYS` occurrences with `fetch.backfill_right_edge_grace_days`.
- `_backfill_apply(paths, staging, plan, source, interval)`: add a trailing `fetch: FetchConfig`; change its `_fetch_all_concurrent(source, plan.per_pair, interval, CliConstants.FETCH_CONCURRENCY, mirror.root_for(paths))` call to `_fetch_all_concurrent(source, plan.per_pair, interval, fetch, mirror.root_for(paths))`.
- `backfill_pipeline(...)`: add `fetch: FetchConfig = FetchConfig()` as the first keyword-only arg, and update closures:

```python
def backfill_pipeline(
    paths: DatasetPaths,
    interval: str,
    arg_to: dt.date,
    source: Source,
    *,
    fetch: FetchConfig = FetchConfig(),
    dry_run: bool = False,
) -> None:
    """Extend every TRADING pair in the index to arg_to. Non-TRADING pairs are silently skipped."""
    plan_fn = lambda d: _backfill_plan(d, interval, arg_to, source, fetch)
    apply_fn = lambda paths, s, p: _backfill_apply(paths, s, p, source, interval, fetch)
    _execute_mutation(paths, "backfill", plan_fn, apply_fn, dry_run=dry_run)
```

- [ ] **Step 6: Thread `fetch` into the rename path**

- `_rename_plan(out_dir, old_symbol, new_symbol, source)`: add a trailing `fetch: FetchConfig`; replace both `CliConstants.RENAME_SYNTH_WARN_DAYS` occurrences (Variant 2 and Variant 1) with `fetch.rename_synth_warn_days`.
- `rename_pipeline(...)`: add `fetch: FetchConfig = FetchConfig()` as the first keyword-only arg, and update the closure:

```python
def rename_pipeline(
    paths: DatasetPaths,
    old_symbol: str,
    new_symbol: str,
    source: Source,
    *,
    fetch: FetchConfig = FetchConfig(),
    dry_run: bool = False,
) -> None:
    """Re-label OLD → NEW under the snapshot+commit discipline (Variant 1 and Variant 2)."""
    plan_fn = lambda d: _rename_plan(d, old_symbol, new_symbol, source, fetch)
    apply_fn = lambda paths, s, p: _rename_apply(paths, s, p)
    _execute_mutation(paths, "rename", plan_fn, apply_fn, dry_run=dry_run)
```

- [ ] **Step 7: Verify no `CliConstants` references remain in pipeline.py**

Run: `grep -n CliConstants cli/data/pipeline.py`
Expected: no output.

- [ ] **Step 8: Run the data-pipeline + download/backfill/rename suites**

Run: `uv run pytest tests/test_data_pipeline.py tests/test_data_download.py tests/test_data_backfill.py tests/test_data_rename.py tests/test_data_e2e.py -q`
Expected: PASS. (All other call sites use the `FetchConfig()` default, which equals the prior `CliConstants` values, so behavior is unchanged.)

- [ ] **Step 9: Commit**

```bash
uv run ruff check --fix && uv run ruff format
git add cli/data/pipeline.py tests/test_data_pipeline.py
git commit -m "refactor(data): inject FetchConfig through download/backfill/rename pipelines"
```

---

## Task 5: Delete `cli/constants.py`

**Files:**
- Delete: `cli/constants.py`, `tests/test_constants.py`

- [ ] **Step 1: Confirm there are no remaining consumers**

Run: `grep -rn "CliConstants\|cli.constants\|cli/constants" cli/ tests/ | grep -v __pycache__`
Expected: no output (Tasks 3 and 4 removed the last references).

- [ ] **Step 2: Delete the files**

```bash
git rm cli/constants.py tests/test_constants.py
```

- [ ] **Step 3: Run the full data suite**

Run: `uv run pytest tests/ -q -k "data or config"`
Expected: PASS, no import errors.

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(config): remove CliConstants (absorbed into [zcrypto.fetch])"
```

---

## Task 6: Reshape the `data` CLI (`cli/data/command.py`)

**Files:**
- Modify: `cli/data/command.py`
- Test: `tests/test_data_command.py`

- [ ] **Step 1: Add the config import + a resolve helper**

After the existing imports in `cli/data/command.py`, add:

```python
from cli.config import ConfigError, load_config, resolve_backup_dir, resolve_data_dir
```

Add this helper just below the `data_app = typer.Typer(...)` definition:

```python
def _load_and_resolve(
    data_dir_flag: Optional[Path], backup_dir_flag: Optional[Path], *, need_backup: bool
):
    """Load zcrypto.toml and resolve the dataset dirs; ConfigError → stderr + exit(1)."""
    cfg = load_config()
    try:
        data_dir = resolve_data_dir(data_dir_flag, cfg)
        backup_dir = resolve_backup_dir(backup_dir_flag, cfg) if need_backup else None
    except ConfigError as e:
        typer.echo(f"ERROR: {e}", err=True)
        raise typer.Exit(code=1) from e
    return cfg, data_dir, backup_dir
```

- [ ] **Step 2: `verify_cmd` — config-resolved `--data-dir`**

Change the option default to `None` and resolve in the body:

```python
@data_app.command("verify")
def verify_cmd(
    data_dir: Optional[Path] = typer.Option(  # noqa: UP007
        None, "--data-dir", help="Compiled dataset dir to validate. Defaults to [zcrypto].data_dir in zcrypto.toml.", file_okay=False
    ),
    silent: bool = typer.Option(False, "--silent", help="Print nothing; convey result via exit code only."),
) -> None:
    """Re-validate an existing dataset against `index.json` and all invariants."""
    _cfg, data_dir, _ = _load_and_resolve(data_dir, None, need_backup=False)
    report = verify_dataset(data_dir, fail_on_gap=True)
    # ... rest of the body unchanged ...
```

- [ ] **Step 3: `download_cmd` — drop positional, add `--backup-dir`, inject fetch**

```python
@data_app.command("download")
def download_cmd(
    pairs_file: Path = typer.Argument(..., help="Plain-text file: one Binance symbol per line.", exists=True, dir_okay=False),
    data_dir: Optional[Path] = typer.Option(  # noqa: UP007
        None, "--data-dir", help="Compiled dataset dir. Defaults to [zcrypto].data_dir in zcrypto.toml.", file_okay=False
    ),
    backup_dir: Optional[Path] = typer.Option(  # noqa: UP007
        None, "--backup-dir", help="Backup dir (raw/ + snapshots/); created if absent. Defaults to [zcrypto].backup_dir.", file_okay=False
    ),
    interval: str = typer.Option("1d", "--interval", help="Kline interval (only 1d supported)."),
    from_date: Optional[str] = typer.Option(  # noqa: UP007
        "2020-01-01", "--from", callback=_from_callback, help="ISO date YYYY-MM-DD."
    ),
    to_date: Optional[str] = typer.Option(  # noqa: UP007
        None, "--to", callback=_to_callback, help="ISO date YYYY-MM-DD (default: yesterday UTC)."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the plan without mutating the dataset."),
) -> None:
    """Fetch Binance spot klines and write/append a Qlib-ready dataset."""
    fd: dt.date = from_date if isinstance(from_date, dt.date) else dt.date(2020, 1, 1)  # type: ignore[assignment]
    td: dt.date = to_date if isinstance(to_date, dt.date) else (dt.date.today() - dt.timedelta(days=1))  # type: ignore[assignment]
    cfg, data_dir, backup_dir = _load_and_resolve(data_dir, backup_dir, need_backup=True)
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    try:
        download_pipeline(
            paths, pairs_file, interval, fd, td, source=BinanceSource(fetch=cfg.fetch), fetch=cfg.fetch, dry_run=dry_run
        )
    except PipelineError as e:
        typer.echo(f"ERROR: {e}", err=True)
        raise typer.Exit(code=1) from e
    if not dry_run:
        typer.echo(f"OK — dataset at {data_dir} now reaches {td}.")
```

- [ ] **Step 4: `backfill_cmd` — drop positional, add `--backup-dir`, inject fetch**

```python
@data_app.command("backfill")
def backfill_cmd(
    data_dir: Optional[Path] = typer.Option(  # noqa: UP007
        None, "--data-dir", help="Compiled dataset dir. Defaults to [zcrypto].data_dir in zcrypto.toml.", file_okay=False
    ),
    backup_dir: Optional[Path] = typer.Option(  # noqa: UP007
        None, "--backup-dir", help="Backup dir (raw/ + snapshots/); created if absent. Defaults to [zcrypto].backup_dir.", file_okay=False
    ),
    interval: str = typer.Option("1d", "--interval", help="Kline interval (only 1d supported)."),
    arg_to_str: Optional[str] = typer.Option(  # noqa: UP007
        None, "--to", callback=_to_callback, help="ISO date YYYY-MM-DD (default: yesterday UTC)."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the plan without mutating the dataset."),
) -> None:
    """Extend every TRADING pair in the index to --to (default yesterday UTC)."""
    arg_to: dt.date = arg_to_str if isinstance(arg_to_str, dt.date) else (dt.date.today() - dt.timedelta(days=1))  # type: ignore[assignment]
    cfg, data_dir, backup_dir = _load_and_resolve(data_dir, backup_dir, need_backup=True)
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    try:
        backfill_pipeline(paths, interval, arg_to, BinanceSource(fetch=cfg.fetch), fetch=cfg.fetch, dry_run=dry_run)
    except PipelineError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    if not dry_run:
        typer.echo(f"backfill complete: {data_dir}")
```

- [ ] **Step 5: `delist_cmd` — drop positional, add `--backup-dir` (no fetch/source)**

```python
@data_app.command("delist")
def delist_cmd(
    symbol: str = typer.Argument(..., help="Symbol to remove (e.g. BTCUSDT)."),
    data_dir: Optional[Path] = typer.Option(  # noqa: UP007
        None, "--data-dir", help="Compiled dataset dir. Defaults to [zcrypto].data_dir in zcrypto.toml.", file_okay=False
    ),
    backup_dir: Optional[Path] = typer.Option(  # noqa: UP007
        None, "--backup-dir", help="Backup dir (raw/ + snapshots/); created if absent. Defaults to [zcrypto].backup_dir.", file_okay=False
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the plan without mutating the dataset."),
) -> None:
    """Remove SYMBOL from the dataset."""
    symbol = symbol.upper()
    _cfg, data_dir, backup_dir = _load_and_resolve(data_dir, backup_dir, need_backup=True)
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    try:
        delist_pipeline(paths, symbol, dry_run=dry_run)
    except PipelineError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    if not dry_run:
        typer.echo(f"delist complete: {symbol} removed from {data_dir}")
```

- [ ] **Step 6: `rename_cmd` — drop positional, add `--backup-dir`, inject fetch**

```python
@data_app.command("rename")
def rename_cmd(
    old_symbol: str = typer.Argument(..., help="Existing symbol to rename (e.g. MATICUSDT)."),
    new_symbol: str = typer.Argument(..., help="Replacement symbol name (e.g. POLUSDT)."),
    data_dir: Optional[Path] = typer.Option(  # noqa: UP007
        None, "--data-dir", help="Compiled dataset dir. Defaults to [zcrypto].data_dir in zcrypto.toml.", file_okay=False
    ),
    backup_dir: Optional[Path] = typer.Option(  # noqa: UP007
        None, "--backup-dir", help="Backup dir (raw/ + snapshots/); created if absent. Defaults to [zcrypto].backup_dir.", file_okay=False
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the plan without mutating the dataset."),
) -> None:
    """Re-label OLD_SYMBOL to NEW_SYMBOL in the dataset (Variant 1: single rename + synthetic gap fill)."""
    old_symbol = old_symbol.upper()
    new_symbol = new_symbol.upper()
    cfg, data_dir, backup_dir = _load_and_resolve(data_dir, backup_dir, need_backup=True)
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    try:
        rename_pipeline(paths, old_symbol, new_symbol, BinanceSource(fetch=cfg.fetch), fetch=cfg.fetch, dry_run=dry_run)
    except PipelineError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    if not dry_run:
        typer.echo(f"rename complete: {old_symbol} → {new_symbol} in {data_dir}")
```

- [ ] **Step 7: Update `tests/test_data_command.py`**

Apply these mechanical updates (read the file; the call shapes are unique enough to edit precisely):

1. **Invocations:** every `runner.invoke(app, ["data", "download", str(backup), str(pairs), ...])`-style call that passed the backup dir **positionally** must pass it as `--backup-dir`, and pass `--data-dir` explicitly so the test never reads the repo-root `zcrypto.toml`. Example transform:
   - before: `["data", "download", str(bk), str(pairs), "--data-dir", str(dd)]`
   - after: `["data", "download", str(pairs), "--data-dir", str(dd), "--backup-dir", str(bk)]`
   Apply the analogous move for `backfill`/`delist`/`rename` (each loses its leading positional backup-dir; `delist` keeps `SYMBOL`, `rename` keeps `OLD NEW` as positionals).
2. **`BinanceSource` stubs:** change the three `monkeypatch.setattr(cmd_mod, "BinanceSource", lambda: object())` lines to `lambda **_kw: object()` (the command now calls `BinanceSource(fetch=…)`). The `patch("cli.data.command.BinanceSource", return_value=src)` line needs no change (it ignores args).
3. **New error-path test** (add):

```python
def test_download_errors_when_no_dirs_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no zcrypto.toml here, so config supplies nothing
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    result = runner.invoke(app, ["data", "download", str(pairs)])
    assert result.exit_code != 0
    assert "no data_dir configured" in result.output or "no backup_dir configured" in result.output
```

4. **New config-default test** (add) — proves the config (not just flags) is honored:

```python
def test_download_uses_config_dirs_when_flags_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "zcrypto.toml").write_text(
        f'[zcrypto]\ndata_dir = "{tmp_path / "data"}"\nbackup_dir = "{tmp_path / "bk"}"\n'
    )
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    monkeypatch.setattr(cmd_mod, "BinanceSource", lambda **_kw: object())
    monkeypatch.setattr(cmd_mod, "download_pipeline", lambda *a, **k: None)
    result = runner.invoke(app, ["data", "download", str(pairs), "--dry-run"])
    assert result.exit_code == 0
```

(If `cmd_mod` isn't already imported in the test module, add `import cli.data.command as cmd_mod`.)

- [ ] **Step 8: Run the command suite**

Run: `uv run pytest tests/test_data_command.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
uv run ruff check --fix && uv run ruff format
git add cli/data/command.py tests/test_data_command.py
git commit -m "feat(data): replace positional BACKUP_DIR with config-resolved --backup-dir/--data-dir"
```

---

## Task 7: Config-resolved `--data-dir` for `experiment` (`cli/experiment/command.py`)

**Files:**
- Modify: `cli/experiment/command.py`
- Test: `tests/test_experiment_command.py`

- [ ] **Step 1: Add the config import + `Optional`**

At the top of `cli/experiment/command.py`, alongside the existing light `resolve_recipe` import, add:

```python
from typing import Optional

from cli.config import ConfigError, load_config, resolve_data_dir
```

- [ ] **Step 2: Change the `--data-dir` option default to `None`**

```python
    data_dir: Optional[Path] = typer.Option(  # noqa: UP007
        None,
        "--data-dir",
        help="Qlib provider directory. Defaults to [zcrypto].data_dir in zcrypto.toml.",
    ),
```

- [ ] **Step 3: Resolve it (before the heavy import / bundle creation)**

Immediately after the `logger.info("recipe-resolved", ...)` line, insert:

```python
    try:
        data_dir = resolve_data_dir(data_dir, load_config()).resolve()
    except ConfigError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc
```

(`run_experiment(recipe, data_dir=data_dir, ...)` then receives the resolved absolute path; the scaffold's own `Path(data_dir).resolve()` is now a no-op.)

- [ ] **Step 4: Add a fast no-config error test** to `tests/test_experiment_command.py`:

```python
def test_experiment_errors_when_no_data_dir_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no zcrypto.toml; no --data-dir flag
    result = runner.invoke(app, ["experiment", "--recipe", "skeleton"])
    assert result.exit_code != 0
    assert "no data_dir configured" in result.output
```

(This must NOT import qlib — the resolve happens before the heavy import. If the test module lacks `runner`/`app`, mirror the existing imports in the file.)

- [ ] **Step 5: Run the experiment command suite (redis-gated e2e will skip without redis)**

Run: `uv run pytest tests/test_experiment_command.py -q`
Expected: PASS (fast tests + the new error test; the e2e skips or runs depending on redis — it passes `--data-dir` explicitly either way).

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix && uv run ruff format
git add cli/experiment/command.py tests/test_experiment_command.py
git commit -m "feat(experiment): resolve --data-dir from zcrypto.toml config"
```

---

## Task 8: Docs + changelog (closeout)

**Files:**
- Modify: `README.md`
- Modify: `docs/iterations-history.md`

- [ ] **Step 1: README — `## Usage` `zcrypto data` subcommands**

In the `##### zcrypto data download …` / `backfill` / `delist` / `rename` sections, remove the `BACKUP_DIR` positional from the synopsis lines and argument tables; add a `--backup-dir` option row (`Backup dir (raw/ + snapshots/); created if absent. Defaults to [zcrypto].backup_dir in zcrypto.toml.`) and adjust `--data-dir` rows to note the default now comes from `zcrypto.toml`. Update the example commands, e.g.:

```bash
echo BTCUSDT > pairs.txt
zcrypto data download pairs.txt --from 2024-01-01 --to 2024-01-31   # dirs from zcrypto.toml
zcrypto data download pairs.txt --backup-dir ./bk --data-dir ./data # explicit overrides
```

- [ ] **Step 2: README — replace the `CliConstants` tuning note**

In the `data download` **Concurrency** paragraph, replace the sentence about editing `CliConstants.FETCH_CONCURRENCY` in `cli/constants.py` with: the fetch knobs live in the `[zcrypto.fetch]` table of `zcrypto.toml` (`fetch_concurrency`, `http_timeout_*`, `http_retry_attempts`, `fetch_progress_log_interval`, `backfill_right_edge_grace_days`, `rename_synth_warn_days`); each overrides a built-in default.

- [ ] **Step 3: README — add a `### Configuration` subsection** (under `## Usage`, before `### Commands` or after the `data` group — wherever it reads best):

Document `zcrypto.toml` (repo root): the `[zcrypto]` `data_dir`/`backup_dir` keys with the **flag → config → error** rule (a command errors if a path is neither flagged nor configured), and the `[zcrypto.fetch]` override-the-default table. Note the file is read relative to the current directory and is committed with working defaults.

- [ ] **Step 4: Verify README renders + toc**

Run: `uv run pre-commit run mdformat --files README.md`
Expected: passes (mdformat may reflow / regenerate the `--maxlevel=4` toc — re-stage if it rewrites).

- [ ] **Step 5: `docs/iterations-history.md` — append the iter-8 entry**

Add at the end:

```markdown
## 2026-06-17 — iter-8: app-level `zcrypto.toml` config

- Added `zcrypto.toml` (committed, repo root) as the app's config home, read by a new framework-agnostic `cli/config.py` (`AppConfig`/`FetchConfig`/`ConfigError`, stdlib `tomllib`).
- Dataset dirs resolve **flag → `[zcrypto]` config → error**: `--data-dir` (all `data` subcommands + `experiment`) and the new `--backup-dir` replace the hardcoded `./data` default and the positional `BACKUP_DIR` argument; an unresolved path prints `ERROR: no <name> configured …` and exits non-zero (no built-in fallback).
- Absorbed `cli/constants.py` (`CliConstants`) into a `[zcrypto.fetch]` table that overrides built-in defaults; the seven knobs (fetch_concurrency, http_timeout_head/get_secs, http_retry_attempts, fetch_progress_log_interval, backfill_right_edge_grace_days, rename_synth_warn_days) are now a `FetchConfig` dataclass dependency-injected from the command layer into the download/backfill/rename pipelines and `BinanceSource`. `cli/constants.py` and `tests/test_constants.py` were deleted.
- README gained a `### Configuration` section; the "edit CliConstants" tuning note was replaced by `[zcrypto.fetch]`.
- This iteration's branch also carried two prep commits: README toc `--maxlevel` 3→4 and a `uv sync --upgrade` dependency refresh.
```

- [ ] **Step 6: Full gate + commit**

Run: `uv run ruff check && uv run ruff format --check && uv run pytest -q`
Expected: full suite PASS (redis-gated experiment tests run if redis is up, else skip).

```bash
git add README.md docs/iterations-history.md
git commit -m "docs(config): document zcrypto.toml usage + iter-8 iterations-history"
```

---

## Self-review checklist (run before declaring done)

1. **Spec coverage:** `zcrypto.toml` (Task 2), loader (Task 1), flag→config→error for both dirs (Tasks 1/6/7), `--backup-dir` replaces positional (Task 6), `[zcrypto.fetch]` + DI + `CliConstants` deletion (Tasks 1/3/4/5), README + changelog (Task 8). ✓
2. **No hardcoded path fallback:** Tasks 6/7 set every `--data-dir`/`--backup-dir` default to `None`; resolution lives only in `cli/config.py`. ✓
3. **Green per task:** Tasks 1–2 additive; Tasks 3–4 keep the ~77 direct pipeline/source call sites working via the `FetchConfig()` default; Task 5 deletes `CliConstants` only after Tasks 3–4 remove its consumers. ✓
4. **Type/name consistency:** `FetchConfig` field names == `[zcrypto.fetch]` keys == the lowercased former `CliConstants` names; `fetch=` keyword is consistent across `BinanceSource` and all three pipelines. ✓
5. **Test hermeticity:** config-resolution tests `monkeypatch.chdir(tmp_path)` so the committed repo-root `zcrypto.toml` is never read; all other command tests pass explicit `--data-dir`/`--backup-dir`. ✓
