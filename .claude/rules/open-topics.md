# Open topics

A **park-for-later** convention for topics worth follow-up — recurring warnings, deferred fixes, "we should investigate X" tangents — that surface during regular work but shouldn't derail the current iteration. Each topic lives in its own markdown file under `docs/open-topics/`; the directory's `README.md` is the index, organized into two top-level categories — `## Research and development` and `## Live trading preparation` — each split into `### Open`, `### Partially done`, and `### Resolved` subsections.

## When to open a topic

The agent considers opening a topic when it notices a **non-trivial** item worth follow-up: a recurring runtime warning, a fix the user explicitly deferred, an intriguing tangent that came up mid-task. Trivial uncertainties (one-off questions answered in the same turn, style nits, already-fixed issues) do **not** qualify — be conservative.

## Mandatory approval gate

The agent **must always ask the user** before creating any topic file. There are no autonomous opens. The natural mechanism is `AskUserQuestion` (or equivalent), offering roughly:

- **Approve** the draft as written → agent writes the file and updates the index.
- **Amend** the draft → user redirects; agent revises and asks again.
- **Skip** → no file is created.

The agent shows its proposed file body (the H1, all sections, and the bullet text for the index) in chat alongside the prompt, so the user reviews concrete text — never a placeholder.

## File path & naming

`docs/open-topics/T<NNNN>-<slug>.md`:

- `<NNNN>` is a 4-digit zero-padded counter. Next serial = one above the highest existing serial in `docs/open-topics/` (the `README.md` is excluded from the count). The counter is **independent** of `docs/specs/` and `docs/plans/` — open topics have their own sequence starting at `0000`.
- `<slug>` is the kebab-case topic title.

## Required file shape

```yaml
---
status: open   # one of: open | partial | resolved
---
```

…followed by, in order:

- `# <Title>` — H1 matching the slug.
- `## Context — what` — one paragraph stating what the topic is.
- `## Why this matters` — the consequence or motivation; why it's worth tracking.
- `## Findings so far` — what is already known (link relevant commits, PRs, files, log lines). `_(none)_` is acceptable when the topic is opened cold.
- `## Suggested next steps` — bullet list of concrete actions a future investigator could take.

A `partial` topic carries a `## Done so far` section between `## Findings so far` and `## Suggested next steps`, recording what landed (link commits/PRs/spec). Its `## Suggested next steps` then lists only the still-open remainder.

## Partially completing a topic

A topic is partially completed by flipping its front-matter `status: open` → `status: partial` **in place**. Then:

- Insert a `## Done so far` section immediately after `## Findings so far`, linking the relevant commits, PRs, and spec that delivered the completed work.
- Trim `## Suggested next steps` to list only the still-open remainder.
- In `docs/open-topics/README.md`, move the topic's bullet from `## Open` to the end of the `## Partially done` section (transition order).

A partially completed topic later closes the normal way (see below).

## Closing a topic

A topic is closed by flipping its front-matter `status` (`open` or `partial`) → `status: resolved` **in place**. The file stays where it is — `docs/open-topics/` is a longitudinal record of investigations and their outcomes. The closing commit (or PR) is where the resolution lives.

## Index sync (every change)

In the same change as opening, partially completing, or closing a topic, edit `docs/open-topics/README.md`:

First, place the topic in the right top-level category and keep it there across its lifecycle:

- **`## Research and development`** — research, experiment, validation, modeling, and data-pipeline topics (the work of finding and proving an edge).
- **`## Live trading preparation`** — topics about going live: paper-trading, live-readiness, production execution, monitoring/alerting, and data freshness for live inference.

Within the chosen category, the topic moves between that category's `### Open` / `### Partially done` / `### Resolved` subsections:

- **Opening:** append a new bullet at the **end of the category's `### Open` subsection**. Within `### Open`, entries stay in serial / creation order (append-only).
- **Partially completing:** **move** the bullet from `### Open` to the **end of the same category's `### Partially done` subsection** (transition order).
- **Closing:** **move** the bullet from `### Open` or `### Partially done` to the **end of the same category's `### Resolved` subsection**. Within `### Resolved`, entries are in resolution order (append-only at close time), which may differ from serial order.

Each bullet is a markdown link to the topic file followed by a one-sentence description, e.g. `- [T0000 — qlib empty-slice warnings](T0000-qlib-empty-slice-warnings.md) — benign numpy diagnostic from qlib's per-step aggregation; revisit when the logger gains warning filters.`

The pre-commit `mdformat` hook covers `docs/open-topics/README.md`; the TOC is generated at `--maxlevel 3` (so it lists the two categories and their `###` subsections) — let `mdformat` regenerate it, never hand-edit the `<!-- mdformat-toc … -->` block.
