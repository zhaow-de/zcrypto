# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`zcrypto` is an early-stage crypto quant project built on [Qlib](https://github.com/microsoft/qlib) (the `pyqlib` dependency), Microsoft's AI-oriented quantitative investment platform. The `cli` package (`cli/__main__.py`) is a [Typer](https://typer.tiangolo.com/) app exposed as the `zcrypto` console script (hatchling build backend). Qlib is not yet wired up (no `qlib.init(...)` call or data directory); expect to build out Qlib-based data, modeling, and strategy code here.

## Repository layout

Standard single-package [uv](https://docs.astral.sh/uv/) project: `pyproject.toml`, `uv.lock`, `.python-version`, and `ruff.toml` all live at the **repo root**, and every `uv` command runs from the root.

- `cli/` — the application package; run via `uv run python -m cli`.
- `.claude/rules/`, `.claude/skills/` — repo-specific Claude Code rules and skills.

## Rules

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

- State assumptions explicitly; mark each as *validated / assumed / unknown*.
- If multiple interpretations exist, present 2–3 with tradeoffs — don't pick silently.
- Distinguish *symptom* ("button is slow") from *problem* ("users abandon checkout").
- Name confidence on non-obvious choices: *high / medium / low*.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked. No "while I'm here."
- No abstractions for single-use code.
- No flexibility, configurability, or error handling that wasn't requested.
- If you write 200 lines and it could be 50, rewrite it.

Self-check: "Would a senior engineer call this overcomplicated?" Complexity is rarely a sign of intelligence — more often, it's a sign of confusion.

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

Transform vague tasks into verifiable goals:

| Weak               | Strong                                                                  |
| ------------------ | ----------------------------------------------------------------------- |
| "Add validation"   | "Invalid inputs rejected with clear messages; tests cover each case"    |
| "Fix the bug"      | "Failing test reproduces it; passes after fix; no regression elsewhere" |
| "Refactor X"       | "Tests pass identically before and after"                               |

For user-facing work, acceptance covers three layers:

- **Functional** — tests pass; edge cases handled
- **User-facing** — a real user flow completes end-to-end
- **Operational** — observable in production (logs, errors, analytics)

For multi-step work, state a brief plan:

```
1. [step] → verify: [check]
2. [step] → verify: [check]
3. [step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## Tooling

- Package/dependency manager: **uv** (`pyproject.toml` + `uv.lock`). Do not edit `uv.lock` by hand.
- Python is pinned to **3.12** (`.python-version`, `requires-python = "==3.12.*"`).
- Run all Python through uv so the locked environment is used.

## Commands

```bash
uv sync                          # install/refresh the locked environment (incl. dev group)
uv run python -m cli [args]      # run the CLI (module entry point; mirrors .vscode/launch.json)
uv run zcrypto [args]            # run the CLI via the installed console script

uv run pytest                    # run tests
uv run pytest path/to/test.py::test_name   # run a single test
uv run coverage run -m pytest && uv run coverage report   # tests with coverage

uv run ruff check --fix          # lint (import sorting) + autofix
uv run ruff format               # format
uv run pre-commit install           # one-time: activate the commit-time hook gate
uv run pre-commit run --all-files   # run the full pre-commit suite
uv add <pkg>            # add new deps
uv add --dev <pkg>      # add new dev deps
```

Tests live in `tests/` (pytest + Typer's `CliRunner`); coverage is reported to Coveralls by `.github/workflows/coverage.yml` on push to `develop`/`main`.

## Conventions

- **Ruff** is the linter and formatter: line length 132, double quotes, import sorting enabled (`select = ["I"]`). Run ruff before committing.
- **pre-commit** is the gate for commits and runs ruff, yamllint, mdformat, and standard hygiene hooks. `mdformat` formats Markdown and regenerates the README table of contents — don't hand-maintain it.
- **pre-commit may rewrite files** (mdformat reflows Markdown; end-of-file fixer; trailing-whitespace) and abort the commit; re-stage and re-commit (never `--no-verify`).
- **Versioning** is commitizen-managed (`.cz.toml`). `cz bump` (run by the `/release` skill) is the source of truth for the version and updates both `pyproject.toml` and the README `Version` badge — don't hand-edit either or they'll drift.
- **Workflow conventions** live in `.claude/rules/`: branch model (`branch-workflow.md`), PR title/body + co-author trailer (`pull-requests.md`), commit messages (`commit-messages.md`), README Usage (`readme-usage.md`), and the iterations-history entry every plan must end with (`iterations-history.md`). Consult them before branching, opening a PR, or releasing.

## Project state notes

Per-iteration changelog: [`docs/iterations-history.md`](docs/iterations-history.md). How to maintain it: [`.claude/rules/iterations-history.md`](.claude/rules/iterations-history.md).
