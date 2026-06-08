# CLI Logger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a project-wide CLI logger: plain text to stdout by default, JSONL to a file via `-l/--log <path>`; `--log-level` configurable; qlib's logger captured in both modes; migrate `example`'s developer `print(...)` to the logger.

**Architecture:** A small `cli/logging/` subpackage with one orchestrator (`configure`), two formatters (`JsonLineFormatter`, `PlainTextFormatter`), and a namespace-gated factory (`get_logger`). Root Typer callback parses the two new global flags and calls `configure(path, level)` once, before dispatching. Format follows destination — file ⇒ JSONL, console ⇒ plain text. Qlib's logger is attached to the same handler in every case, plus `qlib.log.set_global_logger_level(...)` clamps qlib's internal manager. Heavy imports stay deferred so `zcrypto --version` remains fast.

**Tech Stack:** Python 3.12, stdlib `logging`, Typer, pyqlib 0.9.7 (`qlib.log.set_global_logger_level`), pytest + Typer `CliRunner`.

**Spec:** `docs/specs/00001-cli-json-logger-design.md`

---

## File map

- Create `cli/logging/__init__.py` — re-exports `configure` and `get_logger`.
- Create `cli/logging/formatters.py` — `JsonLineFormatter` and `PlainTextFormatter`.
- Create `cli/logging/get_logger.py` — `get_logger(name)` returning `logging.getLogger(f"zcrypto.{name}")`.
- Create `cli/logging/config.py` — `configure(path, level)` orchestrator: handler selection, attach to `zcrypto` + `qlib` loggers, set levels, call `qlib.log.set_global_logger_level`. Idempotent.
- Modify `cli/__main__.py` — root callback gains `-l/--log` and `--log-level`, calls `configure(...)` before subcommand dispatch.
- Modify `cli/example/workflow.py` — replace `print(dataset.prepare("train").head().to_string())` at line 46 with a `logger.info(...)` call.
- Modify `README.md` — document the two new global flags under `## Usage`.
- Modify `docs/iterations-history.md` — final closeout task.
- Tests: `tests/test_logging_formatters.py`, `tests/test_logging_config.py`, `tests/test_logging_cli.py`.

**Commit convention:** `<type>(<scope>): <subject>` (Conventional Commits). Scope is `cli` for runtime code and `config` if a commit only touches READMEs/iterations-history. End every commit message with `Co-Authored-By: Claude <your-model> <noreply@anthropic.com>` crediting the model that actually wrote the commit. The iteration's closeout commit (Task 6) also carries `Reviewed-by:` trailers for every distinct review subagent that signed off — see `.claude/rules/commit-messages.md`.

---

## Task 1: Formatters (TDD)

The two formatters are pure functions of a `LogRecord`. They're the riskiest part to get visually right, so they're TDD-first with hand-built `LogRecord` instances — no side effects, fast to iterate.

**Files:**
- Create: `cli/logging/__init__.py` (empty package marker for now; will gain re-exports in Task 3)
- Create: `cli/logging/formatters.py`
- Test: `tests/test_logging_formatters.py`

- [ ] **Step 1: Create the empty package marker**

`cli/logging/__init__.py`:

```python
```

(empty file)

- [ ] **Step 2: Write the failing formatter tests**

`tests/test_logging_formatters.py`:

```python
import json
import logging
import re

import pytest

from cli.logging.formatters import JsonLineFormatter, PlainTextFormatter


def _make_record(
    name="zcrypto.example.workflow",
    level=logging.INFO,
    pathname="/abs/path/to/workflow.py",
    lineno=46,
    msg="show_data: feature head",
    args=(),
    exc_info=None,
    extra=None,
):
    record = logging.LogRecord(name, level, pathname, lineno, msg, args, exc_info)
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
            record.__dict__.setdefault("_zcrypto_extra_keys", set()).add(k)
    return record


def test_json_basic_shape():
    rec = _make_record()
    line = JsonLineFormatter().format(rec)
    obj = json.loads(line)
    assert obj["level"] == "INFO"
    assert obj["logger"] == "zcrypto.example.workflow"
    assert obj["file"] == "workflow.py"
    assert obj["line"] == 46
    assert obj["message"] == "show_data: feature head"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", obj["ts"])
    assert "pid" not in obj and "thread" not in obj
    assert "extra" not in obj
    assert "exception" not in obj


def test_json_includes_extra_when_present():
    rec = _make_record(extra={"head": {"col": [1, 2, 3]}})
    obj = json.loads(JsonLineFormatter().format(rec))
    assert obj["extra"] == {"head": {"col": [1, 2, 3]}}


def test_json_includes_exception_when_present():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = _make_record(exc_info=sys.exc_info())
    obj = json.loads(JsonLineFormatter().format(rec))
    assert "exception" in obj
    assert "ValueError: boom" in obj["exception"]


def test_json_message_uses_args():
    rec = _make_record(msg="hello %s", args=("world",))
    obj = json.loads(JsonLineFormatter().format(rec))
    assert obj["message"] == "hello world"


def test_json_extra_serializes_non_json_native_via_default_str():
    from pathlib import Path

    rec = _make_record(extra={"path": Path("/tmp/x.log")})
    obj = json.loads(JsonLineFormatter().format(rec))
    assert obj["extra"]["path"] == "/tmp/x.log"


def test_plain_text_basic_shape():
    rec = _make_record()
    line = PlainTextFormatter().format(rec)
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} INFO zcrypto\.example\.workflow"
        r" \[workflow\.py:46\] - show_data: feature head",
        line,
    )
    assert "MainThread" not in line and " - PID" not in line


def test_plain_text_qlib_record():
    rec = _make_record(name="qlib.timer", pathname="/abs/log.py", lineno=127, msg="Time cost: 30.891s | Loading data Done")
    line = PlainTextFormatter().format(rec)
    assert " INFO qlib.timer [log.py:127] - Time cost: 30.891s | Loading data Done" in line
```

- [ ] **Step 3: Run tests to confirm they FAIL**

Run: `uv run pytest tests/test_logging_formatters.py -v`
Expected: ImportError on `cli.logging.formatters` (module doesn't exist yet).

- [ ] **Step 4: Implement `cli/logging/formatters.py`**

`cli/logging/formatters.py`:

```python
from __future__ import annotations

import json
import logging
import time

_OMIT_EXTRA_KEYS = set(logging.LogRecord(
    "x", logging.INFO, "x", 0, "", (), None
).__dict__.keys()) | {"message", "asctime"}


class JsonLineFormatter(logging.Formatter):
    """Emit one JSON object per record (file mode)."""

    def format(self, record: logging.LogRecord) -> str:
        ms = int((record.created - int(record.created)) * 1000)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{ms:03d}Z"
        payload: dict = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "file": record.filename,
            "line": record.lineno,
            "message": record.getMessage(),
        }
        extra = {k: v for k, v in record.__dict__.items() if k not in _OMIT_EXTRA_KEYS}
        if extra:
            payload["extra"] = extra
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class PlainTextFormatter(logging.Formatter):
    """qlib-style line, PID/thread stripped (console mode)."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)s %(name)s [%(filename)s:%(lineno)d] - %(message)s",
        )
```

- [ ] **Step 5: Run tests to confirm they PASS**

Run: `uv run pytest tests/test_logging_formatters.py -v`
Expected: all 7 tests pass.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check --fix cli/logging/__init__.py cli/logging/formatters.py tests/test_logging_formatters.py
uv run ruff format cli/logging/__init__.py cli/logging/formatters.py tests/test_logging_formatters.py
git add cli/logging/__init__.py cli/logging/formatters.py tests/test_logging_formatters.py
git commit -m "$(cat <<'EOF'
feat(cli): add JSONL and plain-text log formatters

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `get_logger` namespace gate

Trivial but worth a test so future modules can't bypass the `zcrypto.*` namespace.

**Files:**
- Create: `cli/logging/get_logger.py`
- Test: extended `tests/test_logging_formatters.py` is *not* the right home — create a new file.
- Test: `tests/test_logging_get_logger.py`

- [ ] **Step 1: Write the failing test**

`tests/test_logging_get_logger.py`:

```python
from cli.logging.get_logger import get_logger


def test_get_logger_returns_zcrypto_namespaced_logger():
    logger = get_logger("example.workflow")
    assert logger.name == "zcrypto.example.workflow"


def test_get_logger_with_simple_name():
    assert get_logger("cli").name == "zcrypto.cli"
```

- [ ] **Step 2: Run it to confirm it FAILS**

Run: `uv run pytest tests/test_logging_get_logger.py -v`
Expected: ImportError on `cli.logging.get_logger`.

- [ ] **Step 3: Implement `cli/logging/get_logger.py`**

```python
from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    """Return the project-namespaced logger for `name`."""
    return logging.getLogger(f"zcrypto.{name}")
```

- [ ] **Step 4: Run the test, confirm it PASSES**

Run: `uv run pytest tests/test_logging_get_logger.py -v`
Expected: 2 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix cli/logging/get_logger.py tests/test_logging_get_logger.py
uv run ruff format cli/logging/get_logger.py tests/test_logging_get_logger.py
git add cli/logging/get_logger.py tests/test_logging_get_logger.py
git commit -m "$(cat <<'EOF'
feat(cli): add namespace-gated get_logger factory

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `configure` orchestrator + package re-exports (TDD)

`configure(path, level)` is the wiring everything else depends on. Test the observable wiring (handler type, formatter, level, propagate, qlib clamp) directly with stdlib `logging` introspection — no CLI or subprocess yet.

**Files:**
- Create: `cli/logging/config.py`
- Modify: `cli/logging/__init__.py`
- Test: `tests/test_logging_config.py`

- [ ] **Step 1: Write the failing wiring tests**

`tests/test_logging_config.py`:

```python
import json
import logging
from pathlib import Path

import pytest

from cli.logging.config import configure


@pytest.fixture(autouse=True)
def _reset_loggers():
    yield
    for name in ("zcrypto", "qlib"):
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            lg.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        lg.propagate = True
        lg.setLevel(logging.NOTSET)


def _project_handler(logger: logging.Logger) -> logging.Handler:
    own = [h for h in logger.handlers if getattr(h, "_zcrypto_owned", False)]
    assert len(own) == 1, f"expected exactly one project handler, found {own}"
    return own[0]


def test_console_mode_attaches_stream_handler_with_plain_formatter():
    from cli.logging.formatters import PlainTextFormatter

    configure(None, "INFO")
    for name in ("zcrypto", "qlib"):
        lg = logging.getLogger(name)
        h = _project_handler(lg)
        assert isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        assert isinstance(h.formatter, PlainTextFormatter)
        assert lg.level == logging.INFO
        assert lg.propagate is False


def test_file_mode_attaches_file_handler_with_json_formatter(tmp_path: Path):
    from cli.logging.formatters import JsonLineFormatter

    log = tmp_path / "z.log"
    configure(log, "DEBUG")
    for name in ("zcrypto", "qlib"):
        lg = logging.getLogger(name)
        h = _project_handler(lg)
        assert isinstance(h, logging.FileHandler)
        assert Path(h.baseFilename) == log
        assert isinstance(h.formatter, JsonLineFormatter)
        assert lg.level == logging.DEBUG


def test_configure_is_idempotent(tmp_path: Path):
    log = tmp_path / "z.log"
    configure(log, "INFO")
    configure(log, "INFO")
    for name in ("zcrypto", "qlib"):
        assert len([h for h in logging.getLogger(name).handlers if getattr(h, "_zcrypto_owned", False)]) == 1


def test_qlib_internal_level_clamped(monkeypatch):
    calls = []

    def fake(level: int) -> None:
        calls.append(level)

    monkeypatch.setattr("qlib.log.set_global_logger_level", fake)
    configure(None, "WARNING")
    assert calls == [logging.WARNING]


def test_file_mode_writes_jsonl_end_to_end(tmp_path: Path):
    log = tmp_path / "z.log"
    configure(log, "INFO")
    logging.getLogger("zcrypto.example").info("hello %s", "world")
    for h in logging.getLogger("zcrypto").handlers:
        h.flush()
    lines = [ln for ln in log.read_text().splitlines() if ln.strip()]
    assert lines, "no log lines written"
    obj = json.loads(lines[-1])
    assert obj["logger"] == "zcrypto.example"
    assert obj["message"] == "hello world"
    assert obj["file"] == "test_logging_config.py"
```

- [ ] **Step 2: Run tests to confirm they FAIL**

Run: `uv run pytest tests/test_logging_config.py -v`
Expected: ImportError on `cli.logging.config`.

- [ ] **Step 3: Implement `cli/logging/config.py`**

```python
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from cli.logging.formatters import JsonLineFormatter, PlainTextFormatter

_TARGET_LOGGERS = ("zcrypto", "qlib")


def configure(path: Optional[Path], level: str) -> None:
    """Set up project + qlib loggers. Idempotent across repeated calls."""
    numeric = logging.getLevelName(level)
    if not isinstance(numeric, int):
        raise ValueError(f"invalid log level: {level!r}")

    handler: logging.Handler
    if path is None:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(PlainTextFormatter())
    else:
        handler = logging.FileHandler(Path(path), mode="a", encoding="utf-8")
        handler.setFormatter(JsonLineFormatter())
    handler.setLevel(numeric)
    handler._zcrypto_owned = True  # type: ignore[attr-defined]

    for name in _TARGET_LOGGERS:
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            if getattr(h, "_zcrypto_owned", False):
                lg.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass
        lg.addHandler(handler)
        lg.setLevel(numeric)
        lg.propagate = False

    # qlib caches loggers behind QlibLogger; clamp its internal manager too.
    import qlib.log  # local import keeps `zcrypto --version` from pulling qlib

    qlib.log.set_global_logger_level(numeric)
```

- [ ] **Step 4: Run tests to confirm they PASS**

Run: `uv run pytest tests/test_logging_config.py -v`
Expected: 5 passed (qlib import is real — adds ~1s to the suite; acceptable).

- [ ] **Step 5: Wire up the package re-exports**

`cli/logging/__init__.py`:

```python
from cli.logging.config import configure
from cli.logging.get_logger import get_logger

__all__ = ["configure", "get_logger"]
```

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check --fix cli/logging/config.py cli/logging/__init__.py tests/test_logging_config.py
uv run ruff format cli/logging/config.py cli/logging/__init__.py tests/test_logging_config.py
git add cli/logging/config.py cli/logging/__init__.py tests/test_logging_config.py
git commit -m "$(cat <<'EOF'
feat(cli): add configure() orchestrator for the CLI logger

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Wire root CLI flags + migrate example's debug print (TDD)

Add `-l/--log` and `--log-level` to the root callback, call `configure(...)` before dispatch, replace the `print(...)` in `workflow.py:46` with a logger call. Keep `configure`'s imports lazy at the root so `zcrypto --version` stays fast (stdlib-only path).

**Files:**
- Modify: `cli/__main__.py`
- Modify: `cli/example/workflow.py`
- Test: `tests/test_logging_cli.py`

- [ ] **Step 1: Write the failing CLI integration tests**

`tests/test_logging_cli.py`:

```python
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.__main__ import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_loggers():
    import logging

    yield
    for name in ("zcrypto", "qlib"):
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            lg.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        lg.propagate = True
        lg.setLevel(logging.NOTSET)


def test_version_still_works_without_log_flags():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "zcrypto v" in result.output


def test_log_flag_writes_jsonl_to_file(tmp_path: Path):
    log = tmp_path / "z.log"
    result = runner.invoke(app, ["-l", str(log), "example"])
    assert result.exit_code == 0, result.output
    # stdout must still carry _render's metrics table
    assert "annualized_return" in result.output
    assert "Excess vs ETH" in result.output
    # file must be JSONL with the documented field set
    lines = [ln for ln in log.read_text().splitlines() if ln.strip()]
    assert lines, "log file is empty"
    parsed = [json.loads(ln) for ln in lines]
    for obj in parsed:
        assert set(obj.keys()) >= {"ts", "level", "logger", "file", "line", "message"}
        assert "pid" not in obj and "thread" not in obj
    assert any(obj["logger"].startswith("qlib.") for obj in parsed), "no qlib record captured"


def test_no_log_flag_emits_plain_text_lines_on_stdout():
    result = runner.invoke(app, ["example"])
    assert result.exit_code == 0, result.output
    # at least one qlib INFO and the _render metrics table both land on stdout
    assert " INFO qlib." in result.output
    assert "annualized_return" in result.output


def test_invalid_log_level_errors():
    result = runner.invoke(app, ["--log-level", "TRACE", "--version"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run tests to confirm they FAIL**

Run: `uv run pytest tests/test_logging_cli.py -v`
Expected: most fail because `-l` / `--log-level` are unknown options.

- [ ] **Step 3: Replace `cli/__main__.py` ENTIRELY with:**

```python
from importlib.metadata import version
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"zcrypto v{version('zcrypto')} (with pyqlib-{version('pyqlib')})")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version_: bool = typer.Option(
        None,
        "-v",
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the application version and exit.",
    ),
    log: Optional[Path] = typer.Option(
        None,
        "-l",
        "--log",
        help="Append JSONL logs to this file. If unset, plain-text logs go to stdout.",
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        case_sensitive=False,
        help="Log threshold. One of DEBUG, INFO, WARNING, ERROR.",
    ),
) -> None:
    level = log_level.upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise typer.BadParameter(f"--log-level must be DEBUG|INFO|WARNING|ERROR, got {log_level!r}")

    from cli.logging import configure

    configure(log, level)

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


from cli.example.command import example

app.command(name="example")(example)


if __name__ == "__main__":
    app()
```

Notes:
- `--version` triggers via the `is_eager=True` callback before the body runs, so it still works without log flags (the test asserts this).
- `from cli.logging import configure` is local: stdlib-only path until a subcommand actually runs. `configure` itself locally imports `qlib.log`, so plain `--version` still doesn't pull qlib.
- Keep `from cli.example.command import example` at the bottom for the same reasons as iter-1 (avoids a forward reference to `app` if ruff reorders imports; see `cli/__main__.py` from iter-1).

- [ ] **Step 4: Migrate `cli/example/workflow.py:46`**

Add a module-level logger near the top of `cli/example/workflow.py` (after the existing imports), and replace the `print(...)` call.

Find (top of file, after `from cli.example.config import ...`):

```python
from cli.example.config import BENCHMARK, TEST, TRAIN, VALID, WINDOW
```

Add immediately after:

```python
from cli.logging import get_logger

logger = get_logger("example.workflow")
```

Find:

```python
    if show_data:
        print(dataset.prepare("train").head().to_string())
```

Replace with:

```python
    if show_data:
        logger.info("show_data: feature head", extra={"head": dataset.prepare("train").head().to_dict()})
```

- [ ] **Step 5: Run tests to confirm they PASS**

Run: `uv run pytest tests/test_logging_cli.py -v`
Expected: 4 passed. (`test_log_flag_writes_jsonl_to_file` and `test_no_log_flag_emits_plain_text_lines_on_stdout` each run the full Qlib pipeline; ~1 minute each. They use the bundled CSV exactly like the iter-1 smoke test, so the OpenMP runtime must be installed.)

- [ ] **Step 6: Sanity-check existing tests still pass**

Run: `uv run pytest tests/test_cli.py tests/test_example_command.py -v`
Expected: all pass. `test_example_command.py` runs the full pipeline; the migration moved a `print` but `_render` is unchanged, so the metric-label smoke assertions still hold.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check --fix cli/__main__.py cli/example/workflow.py tests/test_logging_cli.py
uv run ruff format cli/__main__.py cli/example/workflow.py tests/test_logging_cli.py
git add cli/__main__.py cli/example/workflow.py tests/test_logging_cli.py
git commit -m "$(cat <<'EOF'
feat(cli): wire global -l/--log-level flags and migrate example print

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: README usage update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the `## Usage` Options table**

In `README.md`, under `## Usage`, REPLACE the existing options table with the version below (the previous table has only `-v`/`-h`; this adds the two new global flags). Leave the rest of the section, including the existing `### Commands` subsection added in iter-1, unchanged.

The new table:

```markdown
| Option                          | Description                                                                |
| ------------------------------- | -------------------------------------------------------------------------- |
| `-v`, `--version`               | Show the application version and exit.                                     |
| `-l`, `--log <path>`            | Append JSONL logs to this file. If unset, plain-text logs go to stdout.    |
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | Log threshold (default `INFO`). Applies to `zcrypto.*` and qlib alike. |
| `-h`, `--help`                  | Show help and exit.                                                        |
```

(mdformat owns the table-of-contents block — do not hand-edit it. Pre-commit may reflow column widths; that's fine.)

- [ ] **Step 2: Commit (with mdformat retry)**

```bash
MSG="$(cat <<'EOF'
docs(cli): document global log flags in README usage

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
git add README.md && git commit -m "$MSG" || { git add README.md && git commit -m "$MSG"; }
```

---

## Task 6: Full verification + iterations-history closeout

**Files:**
- Modify: `docs/iterations-history.md`

- [ ] **Step 1: Run the full suite under coverage**

Run: `uv run coverage run -m pytest -v && uv run coverage report`
Expected: all tests pass; `cli/logging/*` modules are 100% (or near it). Whole-suite time will be noticeably longer than iter-1 because two new CLI integration tests run the full Qlib pipeline.

- [ ] **Step 2: Lint + format check across the tree**

Run: `uv run ruff check && uv run ruff format --check`
Expected: clean.

- [ ] **Step 3: Append the iterations-history entry**

Add to the bottom of `docs/iterations-history.md`:

```markdown
## 2026-06-08 — iter-2: general CLI logger

- Added a project-wide CLI logger in `cli/logging/`: `configure(path, level)` attaches a single handler to both `logging.getLogger("zcrypto")` and `logging.getLogger("qlib")` (`propagate=False`), and calls `qlib.log.set_global_logger_level(numeric)` so qlib's internal manager respects the same threshold.
- Format follows destination: with `-l/--log <path>`, JSONL is appended to `<path>`; without `-l`, plain-text lines go to stdout. Plain-text format: `%(asctime)s %(levelname)s %(name)s [%(filename)s:%(lineno)d] - %(message)s` (qlib-style minus PID/thread). JSONL fields: `ts` (UTC ISO-8601, ms, trailing `Z`), `level`, `logger`, `file`, `line`, `message`, optional `extra` and `exception`.
- Added two global flags on the root callback: `-l/--log <path>` and `--log-level {DEBUG,INFO,WARNING,ERROR}` (default `INFO`). `--version` keeps its fast path (qlib is imported only when `configure(...)` actually runs).
- Migrated `cli/example/workflow.py`: the `--show-data` debug `print(...)` is now `logger.info("show_data: feature head", extra={"head": ...})`. `_render`'s metrics table stays on `typer.echo` (command result, not a log).
- README `## Usage` documents the new flags. Tests: `tests/test_logging_formatters.py` (formatter shapes), `tests/test_logging_get_logger.py` (namespace gate), `tests/test_logging_config.py` (wiring + idempotency + qlib clamp + end-to-end JSONL write), `tests/test_logging_cli.py` (CLI integration: --version still works; -l writes JSONL with qlib lines captured; no -l writes plain text on stdout; bad --log-level errors).
```

- [ ] **Step 4: Commit closeout (with `Reviewed-by:` trailers)**

Collect the iteration's distinct **review subagent** models (from your subagent-driven run — every spec-reviewer and code-quality-reviewer that signed off, plus any final reviewer) and put one `Reviewed-by:` trailer per distinct model on the closeout commit, after the `Co-Authored-By:` line. Use the full `Name <noreply@anthropic.com>` form per `commit-messages.md`. Example shape (replace with the actual models you used):

```bash
git add docs/iterations-history.md
git commit -m "$(cat <<'EOF'
docs(cli): record iter-2 logger in iterations history

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
Reviewed-by: Claude Sonnet 4.6 <noreply@anthropic.com>
Reviewed-by: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Final green check**

Run: `uv run pytest -q && uv run pre-commit run --all-files`
Expected: tests pass; pre-commit hooks pass (re-stage + re-commit if any hook reflows files).

---

## Self-review notes

- **Spec coverage:** CLI flags + version-still-fast (Tasks 4, 5) ✓; module layout (Tasks 1–3) ✓; JSONL and plain-text record shapes incl. `file:line` and omitted PID/thread (Task 1, asserted in Task 4 too) ✓; qlib capture in both modes incl. `set_global_logger_level` clamp (Task 3 + 4) ✓; `example` migration (Task 4) ✓; tests covering formatters / configure / CLI integration (Tasks 1, 3, 4) ✓; README + iterations-history closeout (Tasks 5, 6) ✓; reviewer trailers on closeout (Task 6) ✓.
- **Type consistency:** `configure(path: Path | None, level: str) -> None` is used identically in `cli/logging/config.py`, `cli/__main__.py`, and the wiring/CLI tests. `get_logger(name: str) -> logging.Logger` is consistent across `cli/logging/get_logger.py`, `cli/logging/__init__.py`, `cli/example/workflow.py`. JSON field names (`ts`/`level`/`logger`/`file`/`line`/`message`/`extra`/`exception`) match between formatter, config end-to-end test, and CLI integration assertions.
- **Known risk:** the `_OMIT_EXTRA_KEYS` set in `JsonLineFormatter` derives keys from a dummy `LogRecord` to avoid manually listing every stdlib attribute; if a Python release adds a new `LogRecord` attribute, it'll be auto-excluded (good) but a `default=str` call in `json.dumps` is the safety net for anything unusual passed via `extra=`.
