# 00001 — General CLI logger (JSONL file / plain-text console)

- **Date:** 2026-06-08
- **Status:** Approved design (pre-plan)
- **Iteration:** iter-2
- **Scope:** Add a project-wide CLI logger with destination-dependent format,
  always intercepting qlib's logger; migrate `cli/example` off its ad-hoc
  `print(...)` call.

## Goal

A single `zcrypto.*` logger used by every CLI module. **Format follows
destination**:

- No `-l` flag → human-readable **plain text** lines on **stdout**.
- `-l <path>` → machine-readable **JSON Lines** (one record per line) to that
  file.

Verbosity is set by `--log-level {DEBUG,INFO,WARNING,ERROR}` (default `INFO`).
Qlib's own log output is **always** intercepted so it flows through the same
handler in the same format as our records. No PID/thread information in either
shape. The `example` subcommand migrates its developer `print(...)` to the
logger; its user-facing metrics table stays on `typer.echo` (a command result,
not a log).

## Background & constraints

- `cli/__main__.py` is a Typer app with a `--version` callback. The
  `example` subcommand uses `typer.echo` for its rendered table and one
  bare `print(dataset.prepare("train").head().to_string())` in
  `cli/example/workflow.py:46` for the `--show-data` debug dump.
- Qlib (`pyqlib` 0.9.7) writes lines like
  `[PID:Thread](2026-06-08 …) INFO - qlib.timer - [log.py:127] - …`
  directly via its own `_QLibLoggerManager`. The module exposes
  `qlib.log.set_global_logger_level(level)` to clamp those, and the
  standard `logging.getLogger("qlib")` to attach handlers.
- Repo rules: README `## Usage` updated in the same change
  (`readme-usage.md`); iterations-history entry as the final plan task
  (`iterations-history.md`); branch + PR per `branch-workflow.md` /
  `pull-requests.md`.

## Decisions (resolved during brainstorming)

| Fork | Decision |
| --- | --- |
| Default destination (no `-l`) | Plain text to **stdout** (not silent). |
| File format | **JSONL** — one JSON object per line. |
| Console format | **Plain text** — qlib-style line, PID/thread stripped. |
| Level flag | `--log-level`, default `INFO`. |
| Qlib logger | **Always** intercepted, both modes. |
| `_render` metrics table | **Stays on `typer.echo`** (user-facing result, not a log). |
| `file:line` in records | Present in both shapes (basename only). |

## CLI surface

Two new global options on the root callback in `cli/__main__.py`. They are
parsed before any subcommand runs, so `zcrypto --version`, `zcrypto example`,
and every future subcommand inherit them.

| Flag | Default | Effect |
| --- | --- | --- |
| `-l <path>`, `--log <path>` | unset | If set, JSONL is appended to `<path>` (`mode="a"`); if unset, plain text is written to stdout. |
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | `INFO` | Threshold applied to both the `zcrypto.*` and `qlib` loggers. |

README `## Usage` table updated to document both flags in the same change.

## Module layout

New subpackage `cli/logging/` (small, independently-testable units):

- `cli/logging/__init__.py` — re-exports `configure(...)` and `get_logger(name)`.
- `cli/logging/config.py` — `configure(path: Path | None, level: str) -> None`.
  Idempotent. Picks the handler:
  - `path is None` → `StreamHandler(sys.stdout)` with `PlainTextFormatter`.
  - `path is not None` → `FileHandler(path, mode="a", encoding="utf-8")` with
    `JsonLineFormatter`.

  Then, in every case, the same handler is attached to:
  - `logging.getLogger("zcrypto")` — level set, `propagate=False`.
  - `logging.getLogger("qlib")` — level set, `propagate=False`.

  And `qlib.log.set_global_logger_level(<numeric>)` is called so qlib's
  internal `_QLibLoggerManager` respects the same threshold (it caches
  loggers separately from the stdlib root).
- `cli/logging/formatters.py` — two `logging.Formatter` subclasses with the
  exact record shapes specified below.
- `cli/logging/get_logger.py` — `get_logger(name: str) -> logging.Logger`
  returns `logging.getLogger(f"zcrypto.{name}")`. No module ever calls
  `logging.getLogger` directly, so the project namespace gate is enforced.

## Record shapes

Both shapes carry `file` and `line` (basename only — matches qlib's existing
`[log.py:127]` style and stays uniform when our and qlib's lines are
interleaved). Both shapes **omit** `pid`, `thread`, `module`, `pathname`,
`funcName`.

**JSONL (file mode):**

```json
{"ts":"2026-06-08T14:23:11.482Z","level":"INFO","logger":"qlib.timer","file":"log.py","line":127,"message":"Time cost: 30.891s | Loading data Done"}
```

Fields:

- `ts` — UTC, ISO-8601 with millisecond precision and trailing `Z`.
- `level` — `"DEBUG"` / `"INFO"` / `"WARNING"` / `"ERROR"` / `"CRITICAL"`.
- `logger` — `record.name` (e.g. `zcrypto.example.workflow`, `qlib.timer`).
- `file` — `record.filename` (basename).
- `line` — `record.lineno` (int).
- `message` — `record.getMessage()` (rendered with args).
- `extra` — only present when the caller passed `extra={...}`; serialized as
  a dict.
- `exception` — only present when `exc_info` was set; serialized via
  `Formatter.formatException`.

Emitted via `json.dumps(payload, ensure_ascii=False, default=str)` so
`Path`/`Timestamp`/`numpy` scalars in `extra=` don't raise inside the
logger.

**Plain text (console mode):**

```
2026-06-08 14:23:11,482 INFO qlib.timer [log.py:127] - Time cost: 30.891s | Loading data Done
2026-06-08 14:23:11,484 INFO zcrypto.example.workflow [workflow.py:46] - show_data: feature head
```

Format string:
`%(asctime)s %(levelname)s %(name)s [%(filename)s:%(lineno)d] - %(message)s`
with the default `%(asctime)s` `YYYY-MM-DD HH:MM:SS,mmm` separator (matches
qlib's existing shape with `[PID:Thread]` stripped). `exc_info` is appended by
the stdlib formatter's default behavior.

## Qlib capture (both modes)

`configure()` always:

1. Attaches the project handler to `logging.getLogger("qlib")`, sets its
   level, and sets `propagate=False` so qlib lines don't double-emit via the
   stdlib root logger.
2. Calls `qlib.log.set_global_logger_level(numeric_level)` so qlib's internal
   manager (which caches loggers behind `QlibLogger`) also clamps below
   threshold.

Result: every qlib line — initialization, timers, backtest progress, warnings
— is routed through our formatter in the active format. The user never sees
qlib's `[PID:Thread](time) …` prefix; that machinery is replaced.

## Migration of `example`

- `cli/example/workflow.py:46` — replace
  `print(dataset.prepare("train").head().to_string())` with

  ```python
  logger.info("show_data: feature head", extra={"head": dataset.prepare("train").head().to_dict()})
  ```

  using a module-level `logger = get_logger("example.workflow")`.
- `cli/example/command.py` — `_render`'s `typer.echo(...)` calls stay as
  they are. The metrics table is the command's user-facing result, not a
  log; keeping it separate also means `zcrypto example` is still
  readable on a terminal even when `-l` redirects logs to a file.
- `cli/__main__.py` — root callback gains the `-l` / `--log-level`
  options and calls `configure(log, log_level)` before dispatching to the
  subcommand.

## Testing

- **Unit — `JsonLineFormatter`:** feed a hand-built `LogRecord`, assert
  `json.loads(formatter.format(record))` equals the expected dict, including
  `file`/`line`, no `pid`/`thread` keys, and that `extra` and `exception`
  surface only when present.
- **Unit — `PlainTextFormatter`:** feed the same record, assert the line
  matches the documented regex, in particular the `[<file>:<line>]` segment
  and the absence of PID/thread markers.
- **Unit — `configure` wiring:** with `path=None` the project handler is
  `StreamHandler(sys.stdout)` and uses the plain formatter; with
  `path=tmp/x.log` it is `FileHandler` and uses the JSON formatter. In both
  cases the `qlib` logger has the same handler attached and
  `propagate=False`, and `qlib.log.set_global_logger_level` was called with
  the matching numeric level. `configure` is idempotent — calling it twice
  in a row leaves exactly one handler on each logger.
- **Integration — CLI (CliRunner):**
  - `zcrypto example`: stdout contains the `_render` metrics table and at
    least one plain-text log line whose `logger` field is `qlib.*` and one
    whose `logger` is `zcrypto.example.*`. No JSON on stdout.
  - `zcrypto -l <tmpfile> example`: the file's non-empty lines each parse as
    JSON, every record has the documented field set, no record has `pid`
    or `thread`, and at least one record has `logger` starting with
    `qlib.`. Stdout contains the `_render` table but no log lines.
- **Regression:** existing `tests/test_example_*.py` still pass — the
  `--show-data` print moved, but `_render` is unchanged so the smoke
  assertions about metric labels still hold.

## Out of scope

Log rotation, syslog/journald handlers, ANSI colour in plain mode, structured
fields beyond the documented set, `--quiet` flag, third-party library log
capture beyond qlib, persistence policy / log-file lifecycle.

## Closeout (repo rules)

- Spec: `docs/specs/00001-cli-json-logger-design.md`; plan reuses serial
  `00001` under `docs/plans/`.
- Final plan task appends a `docs/iterations-history.md` entry.
- Branch `feat/cli-logger` off `develop`; PR titled
  `feat(cli): iter-2 — general JSON/plain-text logger` into `develop`.
- Per-commit `Co-Authored-By:` trailers; reviewer trailers collected on the
  closeout commit per `commit-messages.md`.
