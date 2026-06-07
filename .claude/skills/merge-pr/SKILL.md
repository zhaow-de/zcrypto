---
name: merge-pr
description: Use when a reviewed GitHub pull request is ready to merge and the local clone needs cleanup afterward — e.g. "merge PR #60 and clean up", landing an approved Claude-authored PR into develop. Merge-commit only (never squash or rebase). For gh/GitHub repos with a develop integration branch.
disable-model-invocation: true
model: haiku
allowed-tools: Bash(git status:*), Bash(git checkout:*), Bash(git pull:*), Bash(git branch:*), Bash(git ls-remote:*), Bash(git push:*), Bash(git fetch:*), Bash(gh pr:*), Bash(python3:*)
---

# merge-pr

## Overview

Merging a PR is a shared, hard-to-reverse action. **Gate it on verification first, then clean up local state safely.** Never merge past a failed gate; never touch a dirty worktree. If a gate fails, report exactly what's wrong and ask the user to resolve it manually — do not work around it, do not proceed.

This repo **always merges with a merge commit** (`--merge`) — never squash, never rebase. A merge commit has its own `Co-Authored-By:` trailer (see `.claude/rules/commit-messages.md`).

## When to use

- The user confirms a PR is reviewed/ready and asks to merge it and/or clean up local branches.
- Finishing a Claude-authored PR after the user's review.

**Not for:** opening/creating PRs; deciding *how* to finish a branch (see superpowers:finishing-a-development-branch); merging into `main` (release-only — use the `/release` skill).

## Step 1 — Identify the PR

```bash
gh pr view <number> --json number,headRefName,baseRefName,state,mergeable,mergeStateStatus,reviewDecision,isDraft,statusCheckRollup,body
```

(Omit `<number>` to use the current branch's PR.) Record `number`, `headRefName`, `baseRefName`, and the gate fields below.

Confirm `baseRefName` is `develop`. If it targets `main`, STOP and tell the user (feature work never merges into `main`).

## Step 2 — The merge gate (STOP if ANY fails)

GitHub has no single "ready to merge" field like GitLab's `detailed_merge_status`; readiness is spread across several fields. Pipe the Step 1 JSON through this evaluator — it prints `GATE PASSED` or lists every failing gate:

```bash
gh pr view <number> --json number,headRefName,baseRefName,state,mergeable,mergeStateStatus,reviewDecision,isDraft,statusCheckRollup,body \
  | python3 -c '
import sys, json
d = json.load(sys.stdin)
fails = []
base = d.get("baseRefName")
state = d.get("state")
m = d.get("mergeable")
rollup = d.get("statusCheckRollup") or []
body = d.get("body") or ""
if base != "develop":
    fails.append("base branch is " + repr(base) + ", not develop (feature PRs never merge to main)")
if state != "OPEN":
    fails.append("state is " + repr(state) + ", expected OPEN")
if d.get("isDraft"):
    fails.append("PR is a draft")
if m == "CONFLICTING":
    fails.append("mergeable=CONFLICTING (conflicts) — update the branch and resolve first")
elif m != "MERGEABLE":
    fails.append("mergeable=" + repr(m) + " — GitHub is still computing; re-run in a moment, never merge on UNKNOWN")
if d.get("mergeStateStatus") == "BLOCKED":
    fails.append("mergeStateStatus=BLOCKED (branch protection: a required review or required check is unsatisfied)")
if d.get("reviewDecision") == "CHANGES_REQUESTED":
    fails.append("reviewDecision=CHANGES_REQUESTED (a reviewer requested changes)")
bad = [c for c in rollup if (c.get("conclusion") or c.get("state") or "").upper() in ("FAILURE","ERROR","CANCELLED","TIMED_OUT","STARTUP_FAILURE")]
if bad:
    fails.append(str(len(bad)) + " CI check(s) failing")
if "- [ ]" in body:
    fails.append("PR description has unchecked checklist item(s) (- [ ])")
if fails:
    print("GATE FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("GATE PASSED — ready to merge")
'
```

What each gate covers:

1. **`state == "OPEN"`** and **`isDraft == false`** — not already merged/closed, not a draft.
2. **`mergeable == "MERGEABLE"`** — GitHub computed a clean (conflict-free) merge. `CONFLICTING` is a hard stop; `UNKNOWN` means GitHub is still computing — wait a few seconds and re-run, **never merge on `UNKNOWN`**.
3. **`mergeStateStatus != "BLOCKED"`** — `BLOCKED` means branch protection is unsatisfied (required review missing or a required check failing). `CLEAN`, `UNSTABLE`, `BEHIND`, and `HAS_HOOKS` are all fine for a merge commit (being behind `develop` is reconciled by the merge; non-required checks don't block).
4. **`reviewDecision != "CHANGES_REQUESTED"`** — if reviews aren't required by the repo, `reviewDecision` is null and the user's go-ahead (why this skill was invoked) is the approval. If reviews ARE required, gate 3 (`BLOCKED`) enforces them.
5. **No failing CI** — any `statusCheckRollup` entry in a failing state stops the merge. This repo's `coverage.yml` runs only on push to `develop`/`main` (not on `pull_request`), so a PR usually reports **no checks** — that is fine, not a failure.
6. **Checklist complete** — the PR description has no unchecked `- [ ]` task-list items (GitHub does not enforce these, so the gate parses the body).

**If any gate fails:** report which one and why, ask the user to resolve it manually (update the branch, fix CI, get the review, check the boxes), then **STOP**. Do not merge.

## Step 3 — Merge

```bash
gh pr merge <number> --merge --delete-branch
```

`--merge` creates a merge commit (this repo's only method — never `--squash`, never `--rebase`); `--delete-branch` deletes the remote head branch as part of the merge. The explicit method flag makes the command non-interactive.

## Step 4 — Sync develop (STOP on a dirty worktree)

```bash
git status --porcelain
```

If that prints **anything**, the worktree is dirty: **STOP**. Tell the user to stash/commit first — the PR is already merged, so local cleanup is just deferred; do not switch branches. Otherwise:

```bash
git checkout develop
git pull --ff-only
```

If the pull is not a fast-forward, STOP and report (don't create a merge commit locally).

## Step 5 — Delete the local branch

```bash
git branch -d <headRefName>
```

Run git from the repo root. You switched to `develop` in Step 4, so you're not on the branch being deleted. Because this repo merges with a merge commit, the branch is fully integrated and `-d` succeeds. (If `-d` ever errors "not fully merged" **and** the PR shows merged **and** the remote branch is gone, the work IS integrated — `git branch -D <headRefName>` is then safe.)

## Step 6 — Confirm the remote branch is gone

```bash
git ls-remote --heads origin <headRefName>
```

Empty output = deleted (expected from Step 3). If it still prints a ref, **warn** the user, then delete it:

```bash
git push origin --delete <headRefName>
```

## Step 7 — Fetch all remotes + prune

```bash
git fetch --all --prune
```

Updates every remote and drops local remote-tracking refs whose upstream branch no longer exists.

## Report

Summarize: PR merged (or which gate stopped you), develop synced (or dirty-worktree stop), local + remote branch deleted, prune done.

## Common mistakes

| Mistake | Fix |
|---|---|
| Merging and letting GitHub reject if not ready | Run the Step 2 gate FIRST; stop + ask on any failure |
| Treating `mergeable=UNKNOWN` as ready | GitHub is still computing — wait and re-run; never merge on `UNKNOWN` |
| Forgetting the checklist (GitHub doesn't enforce task lists) | Parse the PR body for `- [ ]` |
| Squashing or rebasing the merge | Always `--merge` (merge commit) — preserves per-commit history and `Co-Authored-By:` trailers |
| `git checkout develop` on a dirty worktree | `git status --porcelain` first; stop if dirty |
| Assuming `--delete-branch` always worked | Verify with `git ls-remote`; warn + delete if still there |
| `git remote prune origin` only | `git fetch --all --prune` (all remotes, fetch + prune) |
