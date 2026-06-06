---
name: dependabot
description: Manage Dependabot dependency-update PRs — list, check out, rebase onto develop, run uv tests + ruff, auto-fix lint/format, push, wait for CI, merge with squash
disable-model-invocation: true
model: claude-haiku
allowed-tools: Bash(git fetch:*), Bash(git checkout:*), Bash(git rebase:*), Bash(git status:*), Bash(git stash:*), Bash(git push:*), Bash(git add:*), Bash(git commit:*), Bash(git log:*), Bash(git branch:*), Bash(gh pr:*), Bash(uv:*), Bash(python3:*), Bash(sleep:*), Read, Glob, Grep, Edit, Write, AskUserQuestion
---

# Dependabot PR Management

Autonomously process Dependabot dependency-update PRs in this repo: check out, rebase onto `develop`, validate, auto-fix routine issues, push, wait for CI, merge.

## Context

- Current branch: !`git branch --show-current`
- Working tree: !`git status --porcelain || echo "clean"`
- All open PRs (filter for `dependabot/` head branches): !`gh pr list`

## Repo specifics

- **Dependabot is configured** at `.github/dependabot.yml` with `target-branch: "develop"` on every ecosystem, so Dependabot opens PRs against **`develop`** (the integration branch) — never `main` (which is release-only per `.claude/rules/branch-workflow.md`). If a Dependabot PR you see here targets `main`, stop and report — that `target-branch` entry has drifted or been removed.
- The Python application lives at the **repo root** (flat layout). Tests, lint, and the lockfile (`uv.lock`) all live at the root; run `uv` commands from the repo root (no `cd src`).
- Pre-commit hooks (`.pre-commit-config.yaml` at repo root) auto-format on every `git commit` (ruff-format, trailing whitespace, etc.). A push after a hook-driven amend may need re-staging — the loop handles it.
- Configured ecosystems: `uv` (updates `pyproject.toml` + `uv.lock`), `github-actions` (updates `.github/workflows/*`), and `pre-commit` (updates `.pre-commit-config.yaml`). This skill processes any `dependabot/` PR regardless of ecosystem.

## Workflow

### Phase 1 — Setup & discovery

1. **Save current state**: stash uncommitted changes (including untracked) so the cleanup phase can restore them:
   ```bash
   git stash push -m "dependabot-skill-temp" --include-untracked 2>/dev/null || true
   ```

2. **Remember the original branch** so the cleanup phase can return to it:
   ```bash
   ORIGINAL_BRANCH=$(git branch --show-current)
   ```

3. **Sort** the Dependabot PRs from context by priority: minor/patch first, major last. Classify each PR by parsing the `from <X> to <Y>` versions in its title and comparing the major components. Within a priority class, oldest first (longest-pending PRs likely need the most rebasing).

4. **Report plan**: list the PRs to be processed, in the chosen order, with their base branch noted (must be `develop` — see "Repo specifics" above).

### Phase 2 — Process each PR (loop)

For each Dependabot PR in the sorted order:

#### 2a. Check out + rebase onto develop

```bash
git fetch origin
gh pr checkout <number>
git rebase origin/develop
```

If the rebase produces conflicts:
- Attempt auto-resolution for simple conflicts (e.g. `uv.lock`: take the Dependabot side since it represents the upgraded lock state).
- Anything non-trivial → **stop and ask** the user via `AskUserQuestion` with the conflict diff.

> **Note:** pushing the rebased branch makes Dependabot stop managing this PR. That is fine — the skill merges it immediately after.

#### 2b. Local validation

Run in this order; stop on the first failure (so the auto-fix step in 2c knows what to attack):

```bash
uv run ruff check
uv run ruff format --check
uv run pytest -q
```

(We do not have a separate type-checker; lint + format-check + tests is the full local gate.)

#### 2c. Auto-fix (if validation fails)

| Failure | Auto-action | Max attempts |
|---|---|---|
| Lint (`ruff check` exits non-zero) | `uv run ruff check --fix` then re-run `ruff check`; analyze any remaining errors and patch manually if obvious. | 3 |
| Format (`ruff format --check` exits non-zero) | `uv run ruff format` (rewrites in place). | 1 |
| Tests fail | Read the traceback; if it is an obvious upgrade-shaped issue (renamed import, changed signature, deprecated kwarg), patch it. Re-run `pytest`. | 3 |

After the cap: **stop and ask** the user. Don't silently keep retrying.

Commit any fixes with our project's commit convention (per `.claude/rules/commit-messages.md`):

```bash
git add -A
git commit -m "$(cat <<'EOF'
fix(config): resolve <symptom> after <package> upgrade

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

If pre-commit reformats during the commit, re-stage and re-commit (NEVER `--no-verify`).

#### 2d. Push + wait for CI + merge

```bash
# The rebase rewrote history, so the push must be forced (lease-guarded).
git push --force-with-lease origin "$(git branch --show-current)"

# Identify the PR number for this branch (or use the number already in the sorted list)
PR_NUMBER=<the number for this PR>

# Poll CI: every 30s, max 10 minutes.
# This repo's coverage.yml runs on push to develop/main, NOT on pull_request,
# so a Dependabot PR usually reports NO checks — that is treated as a pass,
# and the local ruff + pytest gate above is the real merge gate.
deadline=$(( $(date +%s) + 600 ))
state="pending"
while [ "$(date +%s)" -lt "$deadline" ]; do
    state=$(gh pr view "$PR_NUMBER" --json statusCheckRollup | python3 -c '
import sys, json
rollup = (json.load(sys.stdin) or {}).get("statusCheckRollup") or []
if not rollup:
    print("none"); raise SystemExit
def cls(item):
    c = (item.get("conclusion") or item.get("state") or "").upper()
    if c in ("FAILURE", "CANCELLED", "TIMED_OUT", "STARTUP_FAILURE", "ERROR"):
        return "failed"
    if c in ("SUCCESS", "NEUTRAL", "SKIPPED"):
        return "success"
    return "pending"
states = {cls(i) for i in rollup}
print("failed" if "failed" in states else "pending" if "pending" in states else "success")
')
    if [ "$state" = "success" ] || [ "$state" = "none" ] || [ "$state" = "failed" ]; then
        break
    fi
    echo "Waiting for CI... (state: $state)"
    sleep 30
done

# Merge only when CI passed or reported no checks. On a failure — or when the
# 10-minute deadline expires with CI still pending — STOP and ask the user
# (escalation trigger #4); never merge a red or unfinished PR into develop.
if [ "$state" = "success" ] || [ "$state" = "none" ]; then
    # Squash so each dependency bump is a single commit on develop; also
    # deletes the dependabot/ head branch.
    gh pr merge "$PR_NUMBER" --squash --delete-branch
else
    echo "CI state is '$state' (failing, or still pending after 10 min) — skipping merge; surface this PR to the user and stop."
fi
```

### Phase 3 — Cleanup

```bash
git checkout "$ORIGINAL_BRANCH"
git stash pop 2>/dev/null || true
```

Report a summary:
- ✅ Merged PRs (with number + package)
- ⏭️ Skipped PRs (with reasons — e.g. major-version requiring human review, base branch wrong)
- ❌ Failed PRs (with error details — conflicts, persistent test failures, CI failures)

## User escalation triggers

Only pause for user input when:

1. **Merge conflicts** that aren't trivially auto-resolvable (anything beyond `uv.lock` taking the Dependabot side).
2. **Persistent failures** after the per-issue cap in §2c.
3. **Major-version upgrades** where the changelog mentions breaking changes — surface the upgrade summary and ask before merging.
4. **CI failures unrelated to the PR's changes** (e.g. infra flake, pre-existing test that was passing on develop before this branch was opened).
5. **A PR's base branch is not `develop`** (likely `.github/dependabot.yml` `target-branch` misconfigured — surface and stop).

## Key commands reference

```bash
# List all open PRs (filter for dependabot/ head branches in the output)
gh pr list

# View one PR's full state including check rollup, head branch, and title
gh pr view <number> --json statusCheckRollup,headRefName,baseRefName,title

# Check out a PR's head branch by number
gh pr checkout <number>

# Merge with squash + delete head branch
gh pr merge <number> --squash --delete-branch

# CI status snapshot (one-off)
gh pr view <number> --json statusCheckRollup -q '[.statusCheckRollup[].conclusion // .statusCheckRollup[].state]'
```

## Notes

- **Use `gh`, never `glab`** (per `.claude/rules/branch-workflow.md` — GitHub is the remote).
- **Never modify `main` directly.** Dependabot PRs target `develop`; `main` advances only via `/release` (see `.claude/skills/release/`).
- Commit message subject form is `<type>(<scope>): <subject>` (per `.claude/rules/commit-messages.md`); use `fix(config): …` for auto-fix commits since they're cross-cutting tooling fixes, not component-specific.
- End every commit with a `Co-Authored-By:` trailer naming the **actual** executing model (this skill runs on Sonnet — e.g. `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`). Always reflect the real model, never a stale example.
- Prefer separate `uv …` / `git …` lines over composite `(cd X && Y) && Z` commands.
