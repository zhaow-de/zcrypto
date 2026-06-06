# Pull request convention

## Title (iteration PRs)

GitHub PRs that ship an iteration's work use this exact shape:

```
feat(<scope>): iter-<N> — <short description>
```

- `<scope>` is the snake_case component name (e.g. `cli`), or `config` / `build` if cross-cutting — the component, not the iteration tag.
- `<N>` uses the abbreviated tag `iter-<N>` (e.g. `iter-9`), not spelled out as `iteration 9`.
- Em-dash `—` separates the iteration tag from the description.
- Description mirrors the spec's goal sentence.

## Body

Open PRs using the template at `.github/pull_request_template.md`. Because `gh pr create --body "…"` **bypasses** that template, when you create a PR with `--body` you must mirror the same structure by hand.

**Required, in order:**

1. `## Summary` — one or two sentences mirroring the spec's goal.
2. `## Spec / Plan` — links to the `docs/specs/…` and `docs/plans/…` that produced the PR (`N/A — <reason>` if there was none).
3. the flexible middle (below),
4. `## Checklist`,
5. the aggregated `Co-Authored-By:` trailer (see below).

**Flexible middle:** between Spec/Plan and Checklist, add whatever sections fit the change — a *menu, not a mandate*: `## Changes`, `## Test plan`, `## Migration / compatibility`, `## Risks`, `## Screenshots`, `## Out of scope`, `## Follow-ups`. Scale to complexity and mirror the spec — a trivial PR may add none, a large one several.

### Co-author trailer (PR description)

End the PR body with a single trailer aggregating the **distinct** Claude models that co-authored the PR's commits — deduplicated, **names only** (drop the `<email>`), joined with `; `:

```
Co-Authored-By: Claude Opus 4.8; Claude Sonnet 4.6
```

Derive it from the PR's commits (preserving first-seen order), where `<base>` is the PR's base branch (usually `develop`):

```bash
git log <base>..HEAD --pretty='%(trailers:key=Co-authored-by,valueonly)' \
  | sed '/^$/d' | sed 's/ <[^>]*>//' | awk '!seen[$0]++' | paste -sd , - | sed 's/,/; /g'
```

(`paste -sd ','` joins with a single delimiter, then `sed` expands each into `; ` — a multi-char `paste -sd '; '` would alternate the two characters and drop the space.)

Regenerate the trailer whenever the PR description changes. This aggregated form is for the PR **description only** — per-commit `Co-Authored-By:` trailers stay as-is (one per commit, full `Name <noreply@anthropic.com>` form) per `commit-messages.md`.

## Target branch

Feature and iteration PRs target **`develop`** (see `branch-workflow.md`). Release PRs are opened by the `/release` skill from a `release/<timestamp>` branch **into `main`**, titled `Release v<major>.<minor>.<patch>` — you don't write those by hand.

See `commit-messages.md` for the per-commit convention and `branch-workflow.md` for how PRs are opened.
