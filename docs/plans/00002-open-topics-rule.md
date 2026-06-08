# `open-topics` Rule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new agent rule and `docs/open-topics/` directory for parking topics worth follow-up; expand the `mdformat` pre-commit hook to cover the new index.

**Architecture:** Pure docs/config iteration — no Python touched. Three new/modified docs: the rule text in `.claude/rules/open-topics.md`, the index in `docs/open-topics/README.md`, and the cross-reference line in `CLAUDE.md`. One config tweak: expand `mdformat`'s `files:` regex in `.pre-commit-config.yaml` to cover the new index (the existing project README stays in scope).

**Tech Stack:** Markdown, pre-commit + mdformat (with `mdformat-gfm` and `mdformat-toc` plugins), conventional commits.

**Spec:** `docs/specs/00002-open-topics-rule-design.md`

---

## File map

- Create `.claude/rules/open-topics.md` — the rule text (single-purpose prose, no YAML front-matter, same style as the other rule files).
- Create `docs/open-topics/README.md` — the index file: short prose, mdformat-managed TOC, `## Open` and `## Resolved` subsections, both initially placeholder.
- Modify `.pre-commit-config.yaml` — replace the mdformat hook's `files: ^README\.md$` with the verbose multi-line `(?x)` form covering both files.
- Modify `CLAUDE.md` — append `open-topics.md` to the rules roll-call line under **Conventions**.
- Modify `docs/iterations-history.md` — closeout entry as the final task.

**Commit convention:** `<type>(<scope>): <subject>` (Conventional Commits). Scope is `config` for cross-cutting docs/config changes. End each commit with a `Co-Authored-By: Claude <your-model> <noreply@anthropic.com>` trailer; the closeout commit (Task 4) also carries `Reviewed-by:` trailers for every distinct review subagent that signs off — see `.claude/rules/commit-messages.md`.

---

## Task 1: Add the `open-topics` rule text

The rule file is single-purpose prose matching the existing style in `.claude/rules/` (no YAML front-matter, short paragraphs, code fence for the front-matter snippet).

**Files:**
- Create: `.claude/rules/open-topics.md`

- [ ] **Step 1: Create `.claude/rules/open-topics.md`**

```markdown
# Open topics

A **park-for-later** convention for topics worth follow-up — recurring warnings, deferred fixes, "we should investigate X" tangents — that surface during regular work but shouldn't derail the current iteration. Each topic lives in its own markdown file under `docs/open-topics/`; the directory's `README.md` is the index, split into `## Open` and `## Resolved` subsections.

## When to open a topic

The agent considers opening a topic when it notices a **non-trivial** item worth follow-up: a recurring runtime warning, a fix the user explicitly deferred, an intriguing tangent that came up mid-task. Trivial uncertainties (one-off questions answered in the same turn, style nits, already-fixed issues) do **not** qualify — be conservative.

## Mandatory approval gate

The agent **must always ask the user** before creating any topic file. There are no autonomous opens. The natural mechanism is `AskUserQuestion` (or equivalent), offering roughly:

- **Approve** the draft as written → agent writes the file and updates the index.
- **Amend** the draft → user redirects; agent revises and asks again.
- **Skip** → no file is created.

The agent shows its proposed file body (the H1, all sections, and the bullet text for the index) in chat alongside the prompt, so the user reviews concrete text — never a placeholder.

## File path & naming

`docs/open-topics/<NNNNN>-<slug>.md`:

- `<NNNNN>` is a 5-digit zero-padded counter. Next serial = one above the highest existing serial in `docs/open-topics/` (the `README.md` is excluded from the count). The counter is **independent** of `docs/specs/` and `docs/plans/` — open topics have their own sequence starting at `00000`.
- `<slug>` is the kebab-case topic title.

## Required file shape

```yaml
---
status: open
---
```

…followed by, in order:

- `# <Title>` — H1 matching the slug.
- `## Context — what` — one paragraph stating what the topic is.
- `## Why this matters` — the consequence or motivation; why it's worth tracking.
- `## Findings so far` — what is already known (link relevant commits, PRs, files, log lines). `_(none)_` is acceptable when the topic is opened cold.
- `## Suggested next steps` — bullet list of concrete actions a future investigator could take.

## Closing a topic

A topic is closed by flipping its front-matter `status: open` → `status: resolved` **in place**. The file stays where it is — `docs/open-topics/` is a longitudinal record of investigations and their outcomes. The closing commit (or PR) is where the resolution lives.

## Index sync (every change)

In the same change as opening or closing a topic, edit `docs/open-topics/README.md`:

- **Opening:** append a new bullet at the **end of the `## Open` section**. Within `## Open`, entries stay in serial / creation order (append-only).
- **Closing:** **move** the bullet from `## Open` to the **end of the `## Resolved` section**. Within `## Resolved`, entries are in resolution order (append-only at close time), which may differ from serial order.

Each bullet is a markdown link to the topic file followed by a one-sentence description, e.g. `- [00000 — qlib empty-slice warnings](00000-qlib-empty-slice-warnings.md) — benign numpy diagnostic from qlib's per-step aggregation; revisit when the logger gains warning filters.`

The pre-commit `mdformat` hook covers `docs/open-topics/README.md`; let it regenerate the TOC — never hand-edit the `<!-- mdformat-toc … -->` block.
```

- [ ] **Step 2: Quick visual sanity check**

Run: `cat .claude/rules/open-topics.md | head -20`
Expected: file starts with `# Open topics` and the first paragraph mentions `docs/open-topics/`.

- [ ] **Step 3: Commit**

```bash
git add .claude/rules/open-topics.md
git commit -m "$(cat <<'EOF'
feat(config): add open-topics agent rule

Codifies a park-for-later convention: topics worth follow-up are
proposed by the agent and, after explicit user approval, parked as
serial-numbered markdown files under docs/open-topics/ with a status
front-matter and a single-line bullet in the index.

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add the index file and expand `mdformat` scope (one commit)

These two changes are coupled: the new README only becomes mdformat-managed when the hook's `files:` regex is widened. Landing them together keeps history clean and lets pre-commit lint the new file the moment it appears.

**Files:**
- Create: `docs/open-topics/README.md`
- Modify: `.pre-commit-config.yaml`

- [ ] **Step 1: Create `docs/open-topics/README.md`**

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

- [ ] **Step 2: Modify `.pre-commit-config.yaml` — replace the mdformat hook's `files:` line**

Find (around line 32-39):

```yaml
  - repo: https://github.com/hukkin/mdformat
    rev: 1.0.0
    hooks:
    - id: mdformat
      additional_dependencies:
      - mdformat-gfm
      - mdformat-toc
      files: ^README\.md$
```

Replace the `files:` line with the verbose multi-line form:

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

The `(?x)` flag (Python `re` verbose mode) makes whitespace and newlines inside the regex non-significant, so each file sits on its own line; adding a third file later is a one-line diff.

- [ ] **Step 3: Run mdformat over the new index to confirm it's stable**

Run: `uv run pre-commit run mdformat --files docs/open-topics/README.md README.md`
Expected: `Passed`. If mdformat REWROTE either file (e.g. tightened table widths, regenerated TOC, fixed line endings), re-stage and re-run; the rewritten output is canonical.

- [ ] **Step 4: Read back the result to confirm structure**

Run: `cat docs/open-topics/README.md`
Expected: file contains `## Open<a name="open"></a>` and `## Resolved<a name="resolved"></a>`, the TOC block lists both, and the two `_(none yet)_` placeholders are present. No extra sections.

- [ ] **Step 5: Confirm yamllint accepts the multi-line regex**

Run: `uv run pre-commit run yamllint --files .pre-commit-config.yaml`
Expected: `Passed`. If yamllint complains about indentation, the `files: |` block-scalar content must remain indented by at least one level beyond `files:`.

- [ ] **Step 6: Commit**

```bash
git add docs/open-topics/README.md .pre-commit-config.yaml
git commit -m "$(cat <<'EOF'
feat(config): scaffold docs/open-topics index, extend mdformat scope

Adds docs/open-topics/README.md as the empty-state index (Open and
Resolved subsections with mdformat-managed TOC) and widens the mdformat
hook's files: regex via the (?x) verbose form so both READMEs stay
formatter-managed.

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

If pre-commit's mdformat reflows either file on commit and aborts, re-stage and re-commit with the same message:

```bash
git add docs/open-topics/README.md .pre-commit-config.yaml
git commit -m "$(cat <<'EOF'
feat(config): scaffold docs/open-topics index, extend mdformat scope

Adds docs/open-topics/README.md as the empty-state index (Open and
Resolved subsections with mdformat-managed TOC) and widens the mdformat
hook's files: regex via the (?x) verbose form so both READMEs stay
formatter-managed.

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Cross-reference the new rule in `CLAUDE.md`

The **Conventions** section of `CLAUDE.md` enumerates the rules; the new one must be listed so future readers and agents find it via the same line.

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Read the current line**

Run: `grep -n "Workflow conventions live" CLAUDE.md`
Expected: one line near the bottom of the **Conventions** section, listing the existing five rules.

- [ ] **Step 2: Replace the line**

Find (in `CLAUDE.md`):

```markdown
- **Workflow conventions** live in `.claude/rules/`: branch model (`branch-workflow.md`), PR title/body + co-author trailer (`pull-requests.md`), commit messages (`commit-messages.md`), README Usage (`readme-usage.md`), and the iterations-history entry every plan must end with (`iterations-history.md`). Consult them before branching, opening a PR, or releasing.
```

Replace with:

```markdown
- **Workflow conventions** live in `.claude/rules/`: branch model (`branch-workflow.md`), PR title/body + co-author trailer (`pull-requests.md`), commit messages (`commit-messages.md`), README Usage (`readme-usage.md`), the iterations-history entry every plan must end with (`iterations-history.md`), and the open-topics convention for parking follow-up items (`open-topics.md`). Consult them before branching, opening a PR, or releasing.
```

(The change is: replace the word `and` before `the iterations-history…` with a comma; add a new `, and the open-topics convention for parking follow-up items (\`open-topics.md\`)` clause before the trailing sentence.)

- [ ] **Step 3: Verify the change**

Run: `grep -n "open-topics.md" CLAUDE.md`
Expected: matches the new line containing `\`open-topics.md\``.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(config): cross-reference open-topics rule in CLAUDE.md conventions

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Full verification + iterations-history closeout

**Files:**
- Modify: `docs/iterations-history.md`

- [ ] **Step 1: Run the existing pytest suite (sanity — no code changed)**

Run: `uv run pytest -q`
Expected: same pass count as before iter-3 began (no regressions; this iteration touches no Python).

- [ ] **Step 2: Run the full pre-commit suite across all files**

Run: `uv run pre-commit run --all-files`
Expected: every hook passes, in particular `mdformat` (which now lints both READMEs) and `yamllint` (which lints the modified `.pre-commit-config.yaml`).

- [ ] **Step 3: Append the iterations-history entry**

Add to the bottom of `docs/iterations-history.md`:

```markdown
## 2026-06-08 — iter-3: open-topics rule

- Added `.claude/rules/open-topics.md`: a park-for-later convention for topics worth follow-up. The agent **must always ask the user** before creating any topic file; the natural mechanism is `AskUserQuestion` offering approve / amend / skip, with the proposed file body shown inline for review.
- Topic files live at `docs/open-topics/<NNNNN>-<slug>.md` with `<NNNNN>` a 5-digit zero-padded counter independent of `docs/specs/` and `docs/plans/`. Each file carries YAML front-matter `status: open` (closed in place by flipping to `status: resolved`) and a fixed body shape: `# <Title>`, `## Context — what`, `## Why this matters`, `## Findings so far`, `## Suggested next steps`.
- Added `docs/open-topics/README.md` as the index, split into `## Open` and `## Resolved` subsections. Each bullet is a link + one-sentence description; new entries append to the end of their section, so `## Open` is in serial order and `## Resolved` is in resolution order. mdformat manages the TOC (per-file `--maxlevel=2 --minlevel=2`), so only the two section headers appear.
- Expanded the `mdformat` pre-commit hook's `files:` pattern via the verbose `(?x)` form so it now covers both `README.md` and `docs/open-topics/README.md`; specs/plans Markdown remain untouched.
- Cross-referenced the new rule in `CLAUDE.md`'s **Conventions** roll-call line so the rules list stays the single discovery point.
- No code touched; existing pytest suite unchanged. `uv run pre-commit run --all-files` is green.
```

- [ ] **Step 4: Commit closeout (with `Reviewed-by:` trailers)**

Collect the iteration's distinct **review subagent** models (from the subagent-driven run — every spec-reviewer and code-quality-reviewer that signed off, plus any final whole-branch reviewer) and put one `Reviewed-by:` trailer per distinct model on this closeout commit, directly after the `Co-Authored-By:` line. Use the full `Name <noreply@anthropic.com>` form per `commit-messages.md`. Example shape (replace with the actual models you used):

```bash
git add docs/iterations-history.md
git commit -m "$(cat <<'EOF'
docs(config): record iter-3 open-topics rule in iterations history

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
Reviewed-by: Claude Haiku 4.5 <noreply@anthropic.com>
Reviewed-by: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Final green check**

Run: `uv run pytest -q && uv run pre-commit run --all-files`
Expected: tests pass; pre-commit hooks pass. If any hook reflows files on this final pass, re-stage and re-commit (never `--no-verify`).

---

## Self-review notes

- **Spec coverage:** Rule text (Task 1) ✓ — the `.claude/rules/open-topics.md` content embeds every behavior the spec requires: trigger, mandatory approval gate, file path/naming with the independent counter, required front-matter, required body sections, in-place close mechanism, index sync rules for open and close. Index file with `_(none yet)_` placeholders (Task 2) ✓. mdformat scope expansion via verbose regex (Task 2) ✓. CLAUDE.md cross-reference (Task 3) ✓. Iterations-history closeout (Task 4) ✓. Per-commit `Co-Authored-By:` and closeout `Reviewed-by:` trailers (every task's commit step, with closeout aggregating) ✓.
- **Type consistency:** No code, no type signatures — the only consistency surface is the textual names. The rule consistently refers to `## Open` and `## Resolved` (capitalized, exact wording matching the README headings); to `status: open` and `status: resolved` (lowercase, matching the YAML); to `<NNNNN>-<slug>.md` (matching the README example bullet text format). The README's empty-state placeholder is `_(none yet)_` everywhere it appears (in the spec, the rule example, and the README itself).
- **Known risk:** mdformat may reflow `docs/open-topics/README.md` slightly differently than the literal text in Task 2 Step 1 (e.g. table widths, list spacing, TOC link case). The Task 2 Step 3 explicit `pre-commit run mdformat` and Step 6's re-stage loop are the mitigations — the file's *content* is what matters, not its exact byte layout.
