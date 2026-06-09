# Commit message convention

Follow [Conventional Commits v1.0.0](https://www.conventionalcommits.org/en/v1.0.0/).

Format: `<type>(<scope>)<!>: <subject>`

- **type** — one of `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
- **scope** — the snake_case component name (e.g. `cli`); or `config` / `build` for cross-cutting changes.
- **subject** — imperative mood, lowercase, no trailing period.
- **breaking changes** — append `!` after the scope (e.g. `feat(cli)!: ...`); prefer this form. If you also add a descriptive footer, write the token **hyphenated** as `BREAKING-CHANGE:`, not `BREAKING CHANGE:` with a space — a space-form token is not a valid git trailer, so when it shares the footer block with the `Co-Authored-By:` trailer git drops the whole block and the co-author silently vanishes from the PR aggregation (see `pull-requests.md`). Commitizen bumps MAJOR for either spelling.

Within an iteration, each commit is one slice of the work and uses the plain form `<type>(<scope>): <subject>` — do **not** put an `iteration N` or `iter-N` tag in commit messages (that belongs only in the PR title; see `pull-requests.md`).

## Co-authorship trailer

When Claude writes a commit, end the message with a `Co-Authored-By:` trailer crediting the model:

```
Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

Always reflect the **actual** model and version that did the work (e.g. `Claude Opus 4.6`, `Claude Sonnet 4.6`) — never a hardcoded or stale example. Put it as the last line, separated from the body by a blank line.

**Subagent-authored commits:** when a commit is produced by a subagent (e.g. during subagent-driven development), credit the **subagent's own model**, not the orchestrating session's — the trailer names whoever actually wrote the commit. A single branch will then mix trailers (e.g. Sonnet-authored implementation commits alongside Opus-authored spec/plan commits); the PR description aggregates the distinct models into one trailer (see `pull-requests.md`).

## Reviewer trailer

Credit **every** review subagent that signs off on a commit (e.g. during subagent-driven development) with a `Reviewed-by:` trailer on **that commit** — regardless of whether its feedback prompted a change, matching the standard "I reviewed this and vouch for it" meaning. Use the same full form as the co-author trailer, a distinct token, reflecting the reviewer's **actual** model:

```
Reviewed-by: Claude Opus 4.7 <noreply@anthropic.com>
```

A reviewer is **not** an author — always use `Reviewed-by:`, never `Co-Authored-By:` — so authorship and review stay separate and the co-author aggregation never counts a reviewer. (`Reviewed-by` is a space-free, valid git trailer, so it never trips the footer-parsing caveat above.)

**Workflow.** Per-commit attribution preserves which reviewer covered which slice — useful in long iterations where the closeout-commit aggregation alone obscures the per-slice trail. The practical pattern:

- **Defer pushing to remote when feasible.** Subagent-driven development naturally accumulates many local-only commits; keep them local through the review loops and push only at finishing points (PR open, or when explicitly sharing progress). While the commit is still local, amend is free.
- **Amend each commit with its `Reviewed-by:` trailer as soon as that commit's review passes** — same `git commit --amend` flow used for `Co-Authored-By:`. Multiple reviewers on the same commit get one trailer line each.
- **If a feature/fix-branch commit was already pushed before its review completed**, amend the trailer onto it and **force-push the branch** (`git push --force-with-lease`). This repo's `.github/settings.yml` permits force-push on feature/fix branches and on `develop`; the rewrite is localized to the in-flight branch and never reaches `main`.
- **For `main`, do NOT amend or force-push** — that history is sacrosanct. If a post-hoc `main` review occurs in some unforeseen case, skip the per-commit amend and rely on the PR-description aggregation alone.
- **Closeout commit** (the one appending to `docs/iterations-history.md`) doubles as a **fallback home** for any `Reviewed-by:` trailer that couldn't land on its original commit (e.g. a review covering the iteration as a whole, or where amending the original was inconvenient). It is no longer the *primary* home for reviewer attribution — per-commit is.

The PR description aggregates distinct reviewers the same way as co-authors — see `pull-requests.md`. Because aggregation walks all commits in the range, both per-commit and fallback-on-closeout placements produce identical PR-description output.
