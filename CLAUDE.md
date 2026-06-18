# CLAUDE.md

## Project

`zcrypto` is an early-stage crypto quant project built on Qlib. The `cli` package (`cli/__main__.py`) is a Typer app exposed as the `zcrypto` console script. Qlib is wired end-to-end.

## Repository layout

Standard single-package uv project: `pyproject.toml`, `uv.lock`, `.python-version`, and `ruff.toml` all live at the **repo root**, and every `uv` command runs from the root.

- `cli/` — the application package; run via `uv run python -m cli`.
- `.claude/rules/`, `.claude/skills/` — repo-specific Claude Code rules and skills.
- **CLI subcommands** are sibling packages `cli/<name>/`, each with a `command.py`. Single-command ones register in `cli/__main__.py` via `from cli.<name>.command import <fn>` + `app.command(name=...)(...)`; multi-command groups (e.g. `data`) expose a Typer sub-app registered via `app.add_typer(...)`. Loggers are named `get_logger("<package>.<module>")` — in `command.py` or a submodule (e.g. `example.workflow`, `data.pipeline`).
- `zcrypto.toml` — the app's config, loaded by `cli/config.py`.
- `data/`, `runs/` — gitignored output dirs: the compiled Qlib dataset (`zcrypto data`) and experiment run bundles (`zcrypto experiment`, read by `zcrypto rank`).

## Rules

### 1. Think Before Coding

**Don't assume. Surface tradeoffs. Ask when unclear.**

- State assumptions; mark each *validated / assumed / unknown*.
- Multiple interpretations → present 2–3 with tradeoffs; don't pick silently.
- Name confidence on non-obvious choices (*high / medium / low*).
- Distinguish symptom from root problem.
- Unclear? Stop, name what's confusing, ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked. No "while I'm here."
- No abstractions for single-use code.
- No flexibility / configurability / error handling that wasn't requested.
- 200 lines that could be 50? Rewrite it.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- Remove imports / variables / functions that *your* changes made unused.
- Don't delete pre-existing dead code — mention it instead.

The test: every changed line traces directly to the user's request.

### 4. Define Done by Outcome, Not Output

**"Merged" is not "done." Done is "it works and we can tell."**

- Turn vague tasks into verifiable goals: a failing test that reproduces the bug then passes; tests pass identically before/after a refactor; a real flow completes end-to-end.
- Confirm it's observable in production: logs, errors, analytics that show it working (or failing).
- For multi-step work, state a brief plan as `step → verify` lines.

## Tooling

- Package/dependency manager: **uv** (`pyproject.toml` + `uv.lock`). Do not edit `uv.lock` by hand.
- Python is pinned to **3.12** (`.python-version`, `requires-python = "==3.12.*"`).
- Run all Python through uv so the locked environment is used.

## Commands

```bash
uv sync                          # install/refresh the locked environment (incl. dev group)
uv run zcrypto [args]            # run the CLI via the installed console script

uv run pytest                    # run tests
uv run pytest path/to/test.py::test_name   # run a single test

uv run ruff check --fix          # lint (import sorting) + autofix
uv run ruff format               # format
uv run pre-commit run --all-files   # run the full pre-commit suite
uv add <pkg>            # add new deps
uv add --dev <pkg>      # add new dev deps
```

Tests live in `tests/` (pytest + Typer's `CliRunner`).

The full `uv run pytest` suite is slow; prefer targeted `uv run pytest path::test` while iterating, and run the full suite in the background.

`zcrypto experiment` (and its redis-gated tests) need a local Redis — qlib's disk caches use it for read/write locks; start one with `scripts/redis.sh start`.

## Conventions

- **Ruff** is the linter and formatter: line length 132, double quotes, import sorting enabled (`select = ["I"]`). Run ruff before committing.
- **pre-commit** is the gate for commits and runs ruff, yamllint, mdformat, and standard hygiene hooks. `mdformat` is scoped to **only** `README.md`, `docs/open-topics/README.md`, and `docs/research/01.*.md` (it owns their TOCs — don't hand-maintain those). **Every other Markdown file — `CLAUDE.md`, `.claude/rules/`, `docs/iterations-history.md`, `docs/specs|plans/` — is NOT auto-reflowed; format it yourself.**
- **pre-commit may rewrite files** (mdformat reflows Markdown; end-of-file fixer; trailing-whitespace) and abort the commit; re-stage and re-commit (never `--no-verify`).
- **Versioning** is commitizen-managed (`.cz.toml`). `cz bump` (run by the `/release` skill) is the source of truth for the version and updates both `pyproject.toml` and the README `Version` badge — don't hand-edit either or they'll drift.
- **Workflow conventions** live in `.claude/rules/`: branch model (`branch-workflow.md`), PR title/body + co-author trailer (`pull-requests.md`), commit messages (`commit-messages.md`), README Usage (`readme-usage.md`), when/where to write specs & plans (`spec-plan-locations.md`), the iterations-history entry every plan must end with (`iterations-history.md`), and the open-topics convention for parking follow-up items (`open-topics.md`). Consult them before branching, opening a PR, or releasing.
