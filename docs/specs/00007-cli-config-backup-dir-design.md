# iter-8 — App-level `zcrypto.toml`: config-resolved dirs + absorbed operational tuning

**Goal:** Introduce a committed app-level config file (`zcrypto.toml`) as the single home for the CLI's configuration: the two dataset directories (`data_dir`, `backup_dir`) resolve as **flag → config → error**, and the operational tuning currently hardcoded in `cli/constants.py` moves into a `[zcrypto.fetch]` table that **overrides built-in defaults**. The positional `BACKUP_DIR` argument is replaced by an optional `--backup-dir` flag.

## Context & motivation

Two kinds of configuration are scattered across the code today:

1. **Dataset paths** — the `zcrypto data` subcommands take the backup root as a required positional `BACKUP_DIR`, and every command reading the compiled dataset hardcodes `--data-dir` to `./data`. The same paths are retyped on every invocation and the defaults are literals spread across signatures.
2. **Operational tuning** — `cli/constants.py`'s `CliConstants` holds seven low-change knobs (HTTP timeouts/retries, fetch concurrency, progress-log interval, backfill/rename grace days). The current convention is "edit the Python constant"; there is no file-based override.

This iteration centralizes both in one committed `zcrypto.toml`. Paths have **no built-in default** — they must come from a flag or the config, else the command fails fast with a clear message (a missing/edited config becomes an explicit, diagnosable error rather than a silent fallback to a possibly-wrong path). Operational tuning **keeps sensible built-in defaults** and the config merely overrides them, so the tool runs unconfigured. `CliConstants` is retired and its values become the defaults of a typed config object injected into the consuming code.

## Scope of this iteration

This branch is cut from `develop`, which already carries two preparatory commits authored by the user:

- `2d0bdfe docs(README): extend toc to one level deeper` — README `mdformat-toc --maxlevel` 3 → 4 (so the deeper `#####` headings under `zcrypto data` surface in the table of contents).
- `4a05821 chore(deps): bump all pypi dependencies` — `uv sync --upgrade` refresh of the locked dependency versions.

Those two commits ride along in this iteration's PR; this spec covers only the config/CLI work layered on top.

## Components

### 1. Config file — `zcrypto.toml` (repo root, committed)

```toml
[zcrypto]
# Compiled qlib dataset dir (calendars/, instruments/, features/, index.json).
data_dir = "data"
# Durable backup root holding raw/ (downloaded-zip mirror) and snapshots/.
backup_dir = "../zcrypto-data"

# Operational tuning for `zcrypto data` fetching/pipelines. Each key overrides a
# built-in default; omit a key (or the whole table) to use the default shown.
[zcrypto.fetch]
fetch_concurrency = 8              # max parallel HTTP fetches in `data download`
http_timeout_head_secs = 5         # socket timeout for HEAD / small-body requests
http_timeout_get_secs = 60         # socket timeout for daily-zip GETs
http_retry_attempts = 3            # total attempts per HTTP call (transient failures)
fetch_progress_log_interval = 50   # emit a progress log every N completed (pair, date)
backfill_right_edge_grace_days = 7 # right-edge absence tolerated before delist/rename hint
rename_synth_warn_days = 7         # synthetic-gap-fill threshold for a louder rename warning
```

- Committed so a fresh clone has working defaults; users edit it per machine or override the two paths per-invocation with a flag.
- Paths are interpreted relative to the current working directory (the CLI is always run from the repo root, matching how `--data-dir` already defaults to a cwd-relative `./data`). `data_dir = "data"` ≡ today's `./data`; `backup_dir = "../zcrypto-data"` is the user's existing sibling backup root.
- The `[zcrypto.fetch]` values shown are exactly today's `CliConstants` defaults, listed for discoverability.

### 2. Loader — new `cli/config.py` (framework-agnostic)

Dependency-free (reads TOML via stdlib `tomllib`; no new dependency, no `typer` import):

- `CONFIG_FILENAME = "zcrypto.toml"`, `CONFIG_TABLE = "zcrypto"`.
- `class ConfigError(Exception)` — malformed file or an unresolved required setting.
- `@dataclass(frozen=True) class FetchConfig` — the seven operational settings as typed fields, each defaulting to its current `CliConstants` value (`fetch_concurrency=8`, `http_timeout_head_secs=5`, `http_timeout_get_secs=60`, `http_retry_attempts=3`, `fetch_progress_log_interval=50`, `backfill_right_edge_grace_days=7`, `rename_synth_warn_days=7`).
- `@dataclass(frozen=True) class AppConfig` — `data_dir: Path | None`, `backup_dir: Path | None`, `fetch: FetchConfig`.
- `load_config(config_path: Path = Path(CONFIG_FILENAME)) -> AppConfig`:
  - File absent → `AppConfig(data_dir=None, backup_dir=None, fetch=FetchConfig())` (defaults; no error).
  - File present but not valid TOML, `[zcrypto]` not a table, or `[zcrypto.fetch]` not a table → `ConfigError`.
  - `data_dir`/`backup_dir` present but not a non-empty string → `ConfigError`; absent → `None`.
  - `[zcrypto.fetch]` keys: each present key must be a **positive integer**, else `ConfigError`; an **unknown key** in the table → `ConfigError` (catch typos — the set is fixed). Absent keys keep their default.
- `resolve_data_dir(flag_value: Path | None, cfg: AppConfig) -> Path` / `resolve_backup_dir(...)`: flag → config value → `ConfigError` with an actionable message naming both remedies, e.g. `no data_dir configured — set [zcrypto].data_dir in zcrypto.toml or pass --data-dir <path>.`

### 3. Resolution semantics (two kinds)

- **Paths (`data_dir`, `backup_dir`):** `--flag → [zcrypto].<key> → ConfigError` (clear stderr message + non-zero exit). No hardcoded fallback remains in any command signature.
- **Operational tuning (`[zcrypto.fetch]`):** `config value → built-in default`. Never required; never errors on absence (only on a malformed/typo'd entry).

### 4. Wiring — dependency injection (no global state)

`cli/constants.py` and `tests/test_constants.py` are **deleted**; `CliConstants` is replaced by `FetchConfig` injected from the command layer:

- **`cli/data/command.py`** — each command loads `cfg = load_config()` once at the top, resolves its dir(s) (translating `ConfigError` to `ERROR: <msg>` on stderr + non-zero exit), and:
  - `download`/`backfill`/`rename`: build `BinanceSource(fetch=cfg.fetch)` and pass `fetch=cfg.fetch` into the pipeline entry point.
  - `delist`: no source, no fetch settings — only resolves `data_dir`/`backup_dir`.
  - `verify`: resolves `data_dir` only.
- **`cli/data/pipeline.py`** — `download_pipeline`, `backfill_pipeline`, `rename_pipeline` gain a `fetch: FetchConfig` parameter; their bodies (and the internal concurrent-fetch / progress / grace-day helpers) read `fetch.fetch_concurrency`, `fetch.fetch_progress_log_interval`, `fetch.backfill_right_edge_grace_days`, `fetch.rename_synth_warn_days`. `delist_pipeline` is unchanged (consumes none).
- **`cli/data/binance.py`** — `BinanceSource` takes `fetch: FetchConfig` and stores it; its request helpers pass explicit `attempts=self._fetch.http_retry_attempts` and the appropriate `timeout` (`http_timeout_get_secs` / `http_timeout_head_secs`). `_retryable_request` loses its `CliConstants`-based default (callers pass values explicitly).

### 5. CLI signature changes

- Remove the positional `backup_dir: typer.Argument(...)` from `download`, `backfill`, `delist`, `rename`; add `backup_dir: Optional[Path] = typer.Option(None, "--backup-dir", help="Backup dir (raw/ + snapshots/); created if absent. Defaults to [zcrypto].backup_dir in zcrypto.toml.", file_okay=False)` to those four.
- Change `data_dir` on all five `data` subcommands **and** the `experiment` command from `typer.Option(Path("data"), "--data-dir", …)` to `typer.Option(None, "--data-dir", help="Compiled dataset dir. Defaults to [zcrypto].data_dir in zcrypto.toml.", file_okay=False)`, resolved via `resolve_data_dir(...)`. The `experiment` command resolves before any heavy qlib import and still `.resolve()`s to absolute (preserving the chdir-safety fix).
- New invocation shape: `zcrypto data download --backup-dir <dir> pairs.txt` (positional gone); with the committed config, `zcrypto data download pairs.txt` works flagless.

**Unchanged:** `DatasetPaths` (`cli/data/layout.py`) and the pipelines' path handling (`backup_dir`/`data_dir` stay required fields the command layer fills; `mkdir(parents=True, exist_ok=True)` still creates the backup dir). The `example` command (no `--data-dir`). `cli/data/config.py` (URLs, FIELDS, intervals — a different module, not in scope).

### 6. Error UX

Unresolved path → a single clear stderr line + non-zero exit, e.g. `ERROR: no backup_dir configured — set [zcrypto].backup_dir in zcrypto.toml or pass --backup-dir <path>.` A malformed `zcrypto.toml`, a wrong-typed path, a non-positive/non-int fetch value, or an unknown `[zcrypto.fetch]` key likewise surfaces a clear `ERROR: …` rather than being silently ignored.

## Testing

- **`tests/test_config.py`** (new):
  - absent file → `AppConfig(None, None, FetchConfig())` (defaults).
  - reads `data_dir`/`backup_dir`; a missing path key → `None`.
  - `[zcrypto.fetch]` overrides merge over defaults; an absent fetch key keeps its default; a present one wins.
  - malformed TOML, non-string path, non-positive/non-int fetch value, and unknown fetch key each → `ConfigError`.
  - `resolve_data_dir`/`resolve_backup_dir`: flag wins; config used when no flag; neither → `ConfigError` whose message names both `--<flag>` and `[zcrypto].<key>`.
- **`tests/test_data_command.py`** (update): drop the positional `BACKUP_DIR`; cover `--backup-dir` override, config-supplied default, and the neither-provided → non-zero-exit error path; same for `--data-dir`.
- **`tests/test_data_pipeline.py`** (update): the concurrency test passes `FetchConfig(fetch_concurrency=3)` into the pipeline instead of monkeypatching `CliConstants`.
- **`tests/test_data_binance.py`** (update): construct `BinanceSource(fetch=FetchConfig(...))` (e.g. assert retry/timeout use the injected values).
- **`tests/test_experiment_command.py`** (update): existing e2e passes `--data-dir` explicitly (flag path intact). Add a fast test that `experiment` with no `--data-dir` and no config exits non-zero with the config error **without** importing qlib (resolve precedes the heavy import).
- **`tests/test_constants.py`** — deleted with `cli/constants.py`.

## Documentation & changelog

- **README `## Usage`**: remove `BACKUP_DIR` from the synopsis/argument tables of `download`/`backfill`/`delist`/`rename`; document `--backup-dir` and the `--data-dir`-from-config behavior; add a **Configuration** subsection describing `zcrypto.toml` (the `[zcrypto]` paths with flag → config → error precedence, and the `[zcrypto.fetch]` override-the-default table). Replace the existing "tune `CliConstants` in `cli/constants.py`; no env var or CLI flag" note in the `data download` section with a pointer to `[zcrypto.fetch]`. (The committed `--maxlevel=4` toc change surfaces the deeper headings.)
- **`docs/iterations-history.md`**: append the iter-8 entry (final task of the plan) — the config file, the loader (`AppConfig`/`FetchConfig`), the path resolution rule, the `CliConstants` → `[zcrypto.fetch]` migration via DI, and the `BACKUP_DIR` → `--backup-dir` reshaping.

## Out of scope (YAGNI)

- Env-var overrides, a `zcrypto config init`/auto-creation command, interactive prompts, or config-file search up the directory tree (single repo-root `zcrypto.toml` read relative to cwd).
- Changing any default value, timeout, or behavior — this is a pure relocation of where those values live and how they are resolved.

## Branch / PR

- Branch `feat/cli-config-backup-dir`, cut from `develop` (includes the two preparatory commits), PR into `develop`.
- Spec: `docs/specs/00007-cli-config-backup-dir-design.md`; plan: `docs/plans/00007-cli-config-backup-dir.md`.
