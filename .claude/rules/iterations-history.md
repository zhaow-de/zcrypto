# Iterations history

`docs/iterations-history.md` is the project's per-iteration changelog. Appending a new entry to it is the **final task of every implementation plan** — when writing a plan (superpowers:writing-plans), include it explicitly so it's never missed. **Skip the entry for trivial changes** that skip the committed spec/plan (see `spec-plan-locations.md`) — the changelog tracks substantive iterations, not one-file tweaks.

Each entry is a new section at the bottom (`## <YYYY-MM-DD> — <heading>`) followed by a bullet list: one bullet per feature/change/fix, covering what landed, the artifacts/settings/log events it introduced, and any non-obvious behavior.

## Closeout-doc discipline

The iterations-history entry is one instance of a broader rule: **completed-work docs are authored at closeout, when the work is real — never pre-written during planning.** This covers status flips (e.g. flipping an open-topic to `partial`/`resolved`, see `open-topics.md`), "Done so far" sections, the changelog entry itself, and rule/doc text that documents behavior a not-yet-landed feature introduces — that lands with the feature, not during its planning. When writing a plan, capture these as explicit closeout tasks (with the PR/spec links to fill in), not edits made during the planning phase — writing "this is done" while it only exists as a plan reads as done when it isn't, and goes stale if the design shifts. (Codifying a standing convention that already reflects how we work is not a completion claim and isn't gated to closeout.)
