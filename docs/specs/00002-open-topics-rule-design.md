# 00002 — `open-topics` agent rule

- **Date:** 2026-06-08
- **Status:** Approved design (pre-plan)
- **Iteration:** iter-3
- **Scope:** Add a new agent rule and `docs/open-topics/` directory for parking
  topics worth follow-up; expand the `mdformat` pre-commit hook to cover the
  new index file.

## Goal

Codify a **park-for-later** convention. When the agent notices a topic worth
follow-up (a recurring warning, a deferred fix, "we should investigate X"), it
**proposes** opening a markdown file in `docs/open-topics/` and creates the file
**only after the user approves**. Each file carries a `status:` front-matter
(`open` → `resolved` on close, in place). A `docs/open-topics/README.md`
indexes the convention and the topic backlog, split into `## Open` and
`## Resolved` subsections.

## Background & constraints

- `.claude/rules/` already holds five short rule files (`branch-workflow.md`,
  `commit-messages.md`, `iterations-history.md`, `pull-requests.md`,
  `readme-usage.md`, `spec-plan-locations.md`). Style is single-purpose prose,
  no YAML front-matter. The new rule follows the same style.
- `CLAUDE.md` enumerates the rules under a single line in the **Conventions**
  section; that line must gain the new rule for discoverability.
- The `mdformat` pre-commit hook is currently scoped to `^README\.md$` only.
  It must be expanded to also cover `docs/open-topics/README.md`. Other
  Markdown (`docs/specs/**`, `docs/plans/**`, `docs/iterations-history.md`,
  `.claude/rules/**`) stays out of mdformat's scope — those files contain
  code-heavy content that mdformat would reflow awkwardly.
- Repo rules: iterations-history entry on closeout (`iterations-history.md`);
  branch + PR per `branch-workflow.md` / `pull-requests.md`.

## Decisions (resolved during brainstorming)

| Fork | Decision |
| --- | --- |
| Trigger | Proactive + user-initiated; the agent **must always ask the user** before creating the file. |
| File naming | `<NNNNN>-<slug>.md`; 5-digit zero-padded serial; counter independent of `docs/specs/` and `docs/plans/`. |
| Lifecycle | YAML front-matter `status: open` → `status: resolved`; file stays in place when resolved. |
| Seed | No seeded topic files in this iteration. |
| Index format | Subsections `## Open` then `## Resolved`; bullet points with a markdown link + one-sentence description; append-on-action within each section. |
| Resolved ordering | Within `## Resolved`, entries are in resolution (close-time) order, not strictly serial order. |
| `mdformat` scope | Expanded via verbose multi-line regex to also cover `docs/open-topics/README.md`. |
| Index TOC depth | Per-file `<!-- mdformat-toc start --slug=github --maxlevel=2 --minlevel=2 -->` — only the two section headers appear in the TOC, never the bullets. |

## File layout

- **Create** `.claude/rules/open-topics.md` — the rule.
- **Create** `docs/open-topics/README.md` — the index (empty initial state).
- **Modify** `.pre-commit-config.yaml` — expand the `mdformat` hook's `files:`
  pattern to cover both files via the verbose `(?x)` regex form.
- **Modify** `CLAUDE.md` — add `open-topics.md` to the Conventions line.
- **Modify** `docs/iterations-history.md` — closeout entry as the final plan
  task.

## Rule content (`.claude/rules/open-topics.md`)

The rule codifies these behaviors:

- **Trigger.** The agent considers opening a topic when it notices a
  non-trivial item worth follow-up (recurring warning, deferred refactor, an
  intriguing tangent, or an explicit user "park this"). Trivial uncertainties
  do not qualify — be conservative.
- **Approval gate (mandatory).** The agent **must always ask the user** before
  creating any topic file. No autonomous opens. The natural mechanism is
  `AskUserQuestion` (or equivalent), offering the user roughly: **approve** as
  drafted / **amend** the draft / **skip**. The agent presents its proposed
  file body (the H1, sections, bullet text) and the proposed index bullet
  alongside the prompt so the user reviews concrete text, not a placeholder.
- **File path.** `docs/open-topics/<NNNNN>-<slug>.md`. `<NNNNN>` is a 5-digit
  zero-padded counter, next = one above the highest existing serial in
  `docs/open-topics/` (the `README.md` is excluded from the count). The
  counter is **independent** of `docs/specs/` and `docs/plans/`. `<slug>` is
  the kebab-case topic title.
- **Required front-matter.**

  ```yaml
  ---
  status: open
  ---
  ```
- **Required body sections**, in this order, after a `# <Title>` H1:
  - `## Context — what` — one paragraph stating what the topic is.
  - `## Why this matters` — the consequence or motivation; why it's worth
    tracking.
  - `## Findings so far` — what the agent or user already learned (link to
    relevant commits, PRs, files, log lines). `_(none)_` is acceptable when
    the topic is opened cold.
  - `## Suggested next steps` — bullet list of concrete actions a future
    investigator could take.
- **Closing.** A topic is closed by flipping its front-matter
  `status: open` → `status: resolved` in place. The file stays where it is
  — the directory is a longitudinal record of investigations and their
  outcomes. The closing commit (or PR) is where the resolution lives.
- **Index sync (every change).** In the same change as creating or closing a
  topic, edit `docs/open-topics/README.md`:
  - **Opening:** append a new bullet at the **end of the `## Open` section**.
    Within `## Open`, entries stay in serial / creation order (append-only).
  - **Closing:** **move** the bullet from `## Open` to the **end of the
    `## Resolved` section**. Within `## Resolved`, entries are in resolution
    order (append-only at close time), which may differ from serial order.
  - Each bullet: a markdown link to the topic file followed by a
    one-sentence description, e.g.
    `- [T0000 — qlib empty-slice warnings](T0000-qlib-empty-slice-warnings.md) — benign numpy diagnostic from qlib's per-step aggregation; revisit when the logger gains warning filters.`
  - The pre-commit `mdformat` hook covers this file; let it regenerate the
    TOC — never hand-edit the `<!-- mdformat-toc … -->` block.

## `docs/open-topics/README.md` — initial content

```markdown
# Open topics

Topics worth follow-up are parked here, one file per topic. See `.claude/rules/open-topics.md` for the convention.

<!-- mdformat-toc start --slug=github --maxlevel=2 --minlevel=2 -->

- [Open](#open)
- [Resolved](#resolved)

<!-- mdformat-toc end -->

## Open<a name="open"></a>

_(none yet)_

## Resolved<a name="resolved"></a>

_(none yet)_
```

When the first topic is opened, `_(none yet)_` under `## Open` is replaced by
the bullet list. When that topic resolves, its bullet moves into `## Resolved`
(replacing the `_(none yet)_` placeholder there on first move). Default
filesystem sort of the `*.md` files in the directory matches `## Open` order
(both serial-ordered, append-only).

## `.pre-commit-config.yaml` change

Replace the mdformat hook's single-line `files:` pattern with a verbose
multi-line regex. The `(?x)` inline flag tells Python's `re` engine to ignore
whitespace, so each file sits on its own line and adding another file later is
a one-line diff:

```yaml
  - repo: https://github.com/hukkin/mdformat
    rev: 1.0.0
    hooks:
    - id: mdformat
      additional_dependencies:
      - mdformat-gfm
      - mdformat-toc
      files: |
        (?x)^(
            README\.md|
            docs/open-topics/README\.md
        )$
```

Specs/plans Markdown and the rule files remain untouched. TOC depth on the new
file is controlled per-file by the embedded
`<!-- mdformat-toc start --slug=github --maxlevel=2 --minlevel=2 -->` marker
(`max=min=2` → only the two `##` headings appear in the TOC).

## `CLAUDE.md` change

In the **Conventions** section, append `open-topics.md` to the existing
roll-call line so the new rule is discoverable alongside the others:

> Workflow conventions live in `.claude/rules/`: branch model
> (`branch-workflow.md`), PR title/body + co-author trailer
> (`pull-requests.md`), commit messages (`commit-messages.md`), README Usage
> (`readme-usage.md`), the iterations-history entry every plan must end with
> (`iterations-history.md`), and the open-topics convention for parking
> follow-up items (`open-topics.md`). Consult them before branching, opening a
> PR, or releasing.

## Testing

No code changes → no pytest changes. Verification of this iteration is:

- `uv run pre-commit run --all-files` is green; in particular, the expanded
  `mdformat` hook runs against `docs/open-topics/README.md` and accepts it (no
  reflow loop, TOC regenerates with two entries: `Open`, `Resolved`).
- A read-through of the rule (`.claude/rules/open-topics.md`) leaves no
  ambiguous behavior; every "must" has a single interpretation.
- The CLAUDE.md cross-reference line still lists every existing rule plus the
  new one.

## Out of scope

- Seeding any existing topics (e.g. the qlib `Mean of empty slice` warnings)
  — structural-only this iteration.
- Auto-promoting a resolved topic to an iteration spec — manual for now.
- Any change to specs/plans counters or `docs/iterations-history.md`
  machinery.
- Surfacing the open-topics backlog elsewhere (e.g. in the project README or
  in CI summaries).

## Closeout (repo rules)

- Spec: `docs/specs/00002-open-topics-rule-design.md`; plan reuses serial
  `00002` under `docs/plans/`.
- Final plan task appends a `docs/iterations-history.md` entry.
- Branch `feat/open-topics-rule` off `develop`; PR titled
  `feat(config): iter-3 — open-topics rule` into `develop`. Scope is `config`
  because the change is cross-cutting docs/config with no code touched.
- Per-commit `Co-Authored-By:` trailers; `Reviewed-by:` trailers collected on
  the closeout commit per `commit-messages.md` if any review subagents sign
  off.
