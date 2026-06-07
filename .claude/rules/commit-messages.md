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

When a review subagent's feedback is acted on (e.g. during subagent-driven development), credit it with a `Reviewed-by:` trailer — same full form as the co-author trailer, distinct token, reflecting the reviewer's **actual** model:

```
Reviewed-by: Claude Opus 4.7 <noreply@anthropic.com>
```

Put it on the commit its review covers: a review that prompts a fix goes on the **fix commit**; a final approving review that changes nothing goes on the iteration's **closeout commit** (the `iterations-history` one). A reviewer is **not** an author — always use `Reviewed-by:`, never `Co-Authored-By:` — so authorship and review stay separate and the co-author aggregation never counts a reviewer. (`Reviewed-by` is a space-free, valid git trailer, so it never trips the footer-parsing caveat above.) The PR description aggregates distinct reviewers the same way as co-authors — see `pull-requests.md`.
