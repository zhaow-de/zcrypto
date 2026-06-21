---
name: research-loop
description: Use when the user asks to run the unattended / overnight / autonomous research loop (e.g. invokes /research-loop, "run research overnight while I'm away", "keep iterating autonomously"). The autonomous (unattended) research mode that runs reversible experiments — feature/model/comparison research and the heavy compute, sweeps, and tooling they need — with NO questions and NO waiting, holding hard-to-reverse actions and high-stakes judgment for an interactive session, toward the project's max-profitability research goal.
disable-model-invocation: true
---

# research-loop

## Overview

Run the project's research iterations **unattended** — the same brainstorm → spec → plan → subagent-driven execution → A/B verdict → merge cycle this repo runs interactively, but with **zero human interaction**. The human is away; nobody will answer. Your job is to keep the research moving autonomously and leave a reviewable trail.

This is the **standing autonomous procedure**. It is not tied to any particular past run; each run picks up the current backlog and iterates until the morning time-gate.

**Overall goal:** find a Qlib strategy / model / feature / label / data combination that maximizes profitability. Stay in the **research domain** — do NOT switch to live-trading or paper-trading preparation.

## Interactive vs. autonomous: the division of labor

The work splits across two modes. Knowing which side of the line you are on is the **first** thing this loop does. The boundary is **reversibility and judgment — NOT topic, and NOT how heavy the work is.**

- **AUTONOMOUS (this loop, unattended).** Anything **reversible / discardable** runs here, no matter how heavy. It lands on a branch, is reviewable, and a bad result is simply thrown away — so the cost of being wrong is near zero. This explicitly **includes heavy work**: large backtests, big parameter sweeps, long-running experiments, and even **building substantial tooling, harnesses, fetchers, or pipelines** when that scaffolding is itself reversible (a branch you can discard). Heaviness is not a reason to defer; reversibility is what licenses running it unattended. The loop runs the full cycle with no questions and no waiting, leaving a reviewable decision trail, until the morning time-gate.
- **INTERACTIVE (attended, with the human).** Two things wait for an attended session, because their cost-of-being-wrong is high:
  1. **Hard-to-reverse or destructive actions** — deleting or overwriting datasets, anything touching **live / paper trading or production**, anything **published externally** (an upstream issue/PR, a release).
  2. **High-stakes judgment calls** — a major strategic pivot, an architectural decision that **locks in a hard-to-change design**, a "is this good enough to deploy" call. The defining trait is high cost of being wrong, not difficulty.

The reversible experiments the loop does — a new feature set or transform, a different model class or hyperparameters, a new label / horizon, a different universe or top-k / holding / cost preset, a clean A/B against the current best, plus the tooling and compute to run them — are **examples of "reversible," not the definition of the loop's scope.** If a heavy or infrastructural task is reversible, it is in scope.

Live-trading / paper-trading preparation stays **out of this loop entirely** — not because it's heavy, but because it is hard-to-reverse / production-facing and belongs to an attended session.

### The Iron Rule vs. the boundary — how they fit together

These two rules look like they conflict; they do not, because they govern **different kinds of decision**:

- The loop **owns every small, reversible research decision** — which feature, model, label, universe, or knob to try next. For these you **decide → log if it's a subject-matter live-iteration decision (per `.claude/rules/decisions-log.md`) → continue.** A wrong such decision is just a discardable experiment on a branch; throwing it away costs nothing. The Iron Rule (below) tells you to make these yourself, and you do.
- Only a **hard-to-reverse action** or a **high-stakes judgment call** (the two interactive cases above) is reserved for the human. "Judgment work waits for interactive mode" means **that** judgment — irreversible/high-stakes — **not** the ordinary reversible decisions the Iron Rule tells the loop to make.

So there is no contradiction: the loop decides freely on everything cheap-to-reverse, and parks only the rare irreversible/high-stakes step.

### The "park the irreversible step, not the heavy work" rule

Sometimes an iteration's natural path would require a hard-to-reverse action or a high-stakes judgment call the loop should not make alone. When that happens:

1. **Do the reversible parts autonomously — including the heavy compute.** Run the backtests, the sweeps, build the reversible tooling. None of that is gated by the presence of an irreversible step elsewhere in the idea.
2. **Prefer a reversible variant that avoids the irreversible step.** Reframe the hypothesis so the whole thing can run reversibly tonight (e.g. write to a new dataset path instead of overwriting; draft an upstream issue locally instead of filing it). A clean experiment you *can* run reversibly beats a perfect one that needs an irreversible action.
3. **Park ONLY the irreversible / high-stakes step** for the next interactive session — log it (per `.claude/rules/decisions-log.md`, recorded as parked) and/or capture it as an R&D open-topic (per `.claude/rules/open-topics.md`). Then immediately continue with the reversible variant or the next work package.

**Never stop, and never take the irreversible / destructive action unattended.** Parking is not a stop — you park the one step and keep moving. Heavy or infrastructural work is **not** what gets parked; only the irreversible/high-stakes step is.

## The Iron Rule of autonomy

**Never stop to ask. Never wait for input. Never defer a reversible choice to the human.** There is no human to respond — pausing means the loop dies.

When you hit ANY reversible question or decision (a design fork, an ambiguity, an approval gate, a "which option" choice):

1. **List the options** (2-3) and their tradeoffs.
2. **Evaluate** them and **pick the most confident / most beneficial** one.
3. **Log** it — if it's a subject-matter research decision in this live iteration, record it per `.claude/rules/decisions-log.md` (the gate and format live there). Routine tooling/process decisions you still decide, but they're outside the log's gate — don't record them.
4. **Continue** immediately with your pick.

This protocol **replaces** the repo's default "Rule 1: ask when unclear" *for the duration of the loop*. You still surface tradeoffs — but for subject-matter decisions you surface them **into the decisions log**, then decide and proceed. The human reviews `.tmp/decisions.md` later and can correct course; that is the safety net, not a blocking question. (The narrow exception is a genuinely hard-to-reverse action or a high-stakes judgment call — park that one step, per the boundary above; everything reversible, you decide.)

**There are exactly two ways the loop ends — nothing else is a stop:**
1. **The 08:00 Berlin time-gate** (step 10) — the normal end of an overnight run.
2. **A genuinely unrecoverable blocker** you cannot fix after real effort (e.g. the dataset is gone, the environment won't run). Even then: jot what blocked you at the end of `.tmp/decisions.md` before stopping (a free-form stop-note, not a gated decision entry).

Everything else that *feels* like a stopping point is NOT one — keep going:
- **An empty / exhausted open-topics backlog is NOT a stop** → manufacture the next work package (tweak knobs / try a different model — see Constraints & special cases).
- **A failed or negative-result iteration is NOT a stop** → record the verdict, pick the next thread, continue.
- **A mid-execution error is NOT a stop** → diagnose, fix, continue (step 6).
- **A reversible decision/ambiguity is NOT a stop** → decide → log if it's subject-matter (per the rule) → continue (above).
- **An idea with a hard-to-reverse step is NOT a stop** → do the reversible parts (incl. heavy compute), park only that step, run a reversible variant or the next package (the park rule above).

**The approval gates are pre-satisfied.** Invoking the loop IS the human's standing approval. So:
- `superpowers:brainstorming`'s HARD-GATE (design approval before implementing) → satisfied by the recorded decisions + your spec self-review. Proceed to writing-plans without waiting.
- the spec user-review gate → satisfied; do your own self-review and move on.
- the executing-plans / subagent-driven-development handoff → just start; don't ask which mode.
- the PR merge → merge it yourself via `merge-pr` when green (do NOT stop at the PR for human approval, unlike attended mode).

## The loop (one iteration)

1. **Pick a work package.** Source it from the *Suggested next steps* of the **last iteration** (`docs/iterations-history.md`) or the **R&D open-topics** (`docs/open-topics/README.md`, the `## Research and development` Open/Partially-done lists). Keep it **small**: one hypothesis + a suggested validation approach, sized for a single iteration. It may be heavy (a big sweep, a long backtest, building reversible tooling) — that's fine, as long as it's reversible. If its natural path includes a hard-to-reverse action or a high-stakes judgment call, apply the park rule: pick a reversible variant and park only that step. If no feasible topic remains, **create one** by tweaking recipe knobs or trying a different model (see Constraints & special cases).
2. **Brainstorm** it with `superpowers:brainstorming` as a new iteration — autonomously (apply the Iron Rule to every question the skill would ask).
3. **Spec self-review** — run the brainstorming self-review; fix inline. (No user review gate — proceed.)
4. **Plan** with `superpowers:writing-plans`.
5. **Execute** with **`superpowers:subagent-driven-development`** (fresh-subagent-per-task + per-task review + final whole-branch review).
6. **Handle issues mid-execution** — if something breaks (a failing test, a runtime error, a stale lock, a tooling gap), **diagnose and fix it, then continue**. Don't abandon the iteration; don't wait. Use `superpowers:systematic-debugging` for non-trivial failures. Building the missing tooling is fair game when it's reversible; only a hard-to-reverse fix gets parked (work around it tonight; park that step).
7. **Closeout** — produce the **A/B verdict** (the iteration's measured result vs its baseline) and **suggest the next step** based on the result. Write the iterations-history entry.
8. **Capture follow-ups** — if multiple next steps surface, or you discover a better next step than the current backlog, or you spot a new tangent worth tracking (including any parked irreversible/judgment step), write them into `docs/open-topics/` (new `T<NNNN>` topic files + index, per `.claude/rules/open-topics.md`). In unattended mode the open-topics approval gate is pre-satisfied — create them, logging the rationale per `.claude/rules/decisions-log.md`.
9. **Merge** — when everything is green (tests pass, reviews clean), merge the PR with `merge-pr`.
10. **Time-gate** — check **Berlin time** (`TZ=Europe/Berlin date`). If it is **before 08:00**, start the **next** iteration (go to step 1). If it is **08:00 or later**, **stop and wait for the human** — post a concise summary of what landed and the proposed next step.

## Constraints & special cases

- **Research domain only.** Do not start live-trading or paper-trading prep (the live/paper-readiness open-topics) — those are hard-to-reverse / production-facing and out of scope for this loop.
- **Reversibility is the line, not heaviness.** Heavy compute, big sweeps, and building reversible tooling/harnesses/pipelines all run autonomously. Park only a hard-to-reverse action (deleting/overwriting datasets, anything touching live/paper/production, anything published externally) or a high-stakes judgment call — and park only *that step*, per the park rule. Prefer a reversible variant that sidesteps it.
- **qlib bug discovered?** Write an issue draft to `.tmp/qlib-bug-<subject>.md` using the template at `https://github.com/microsoft/qlib/blob/main/.github/ISSUE_TEMPLATE/bug-report.md` (a draft is reversible — actually *filing* it upstream is the irreversible step, so leave that for an interactive session). A local qlib clone for reference/line-citations is at `/Users/zhaow/Projects/qlib`. Keep going by creating a workaround — don't block on it.
- **Out of feasible open topics?** Don't stop — manufacture the next work package: tweak a recipe's knobs (model hyperparameters, label horizon, universe, topk/holding, cost preset) or swap the model (e.g. a different GBDT config, linear, or another qlib model), forming a clean A/B vs the current best. Log the choice per `.claude/rules/decisions-log.md`.
- **Slow tasks** (multi-window re-measures, large fetches, full backtests, big sweeps): run them in the background and **check status about every hour** (a long fallback wakeup) rather than blocking — avoid endless waiting. When harness-tracked background work finishes you're re-invoked automatically. Heavy is fine; just don't block on it.
- **Honesty holds.** Read verdicts on the **cost-adjusted measures the project uses** (e.g. paired cost-adjusted Sharpe, not gross ending value — see the cost-measure open-topic); a negative/null result is a valid, valuable outcome — record it and pick the next thread. Do not fabricate a positive result to keep the loop "successful."

## Red flags — you are about to violate autonomy

If you catch yourself doing any of these, STOP that impulse and apply the Iron Rule (decide → log per the rule → continue) — or, for an irreversible/judgment step, the park rule:

- Drafting a question / `AskUserQuestion` / "I'll ask the human" for a **reversible** decision
- "This decision belongs to the human" — for a reversible research choice (it doesn't; only irreversible/high-stakes does)
- "Rule 1 says ask when unclear"
- "I'll leave a note / draft and wait for them to wake up"
- "The brainstorming HARD-GATE / spec review / merge needs approval first"
- Stopping at the open PR instead of merging it
- Ending the turn while it is still before 08:00 Berlin with green work and a clear next step
- Treating an empty open-topics backlog as a "terminal condition" / reason to stop (manufacture a work package instead)
- Treating a failed iteration or a blocker as the end of the loop (fix it or pivot, then continue)
- **Refusing to run heavy/infrastructural work** because it "feels like infrastructure work" — if it's reversible, run it (only an irreversible/high-stakes step is parked)
- **Taking a hard-to-reverse or destructive action unattended** (overwriting a dataset, touching live/paper/production, publishing externally) — park that step and run a reversible variant

## Rationalizations — and the reality

| Rationalization | Reality |
|---|---|
| "This design choice belongs to the human." | In the loop you own every **reversible research** decision. Log it per `.claude/rules/decisions-log.md`; the human reviews and corrects later. That log IS their involvement. Only a hard-to-reverse action or a high-stakes judgment call waits. |
| "Rule 1 says surface tradeoffs and ask." | Rule 1's *ask* is suspended for reversible decisions. You honor "surface tradeoffs" by listing+evaluating options (logging subject-matter ones), then deciding. Not deciding = the loop dies. |
| "The brainstorming HARD-GATE needs approval before I implement." | Invoking the loop is the standing approval. Your recorded decisions + spec self-review substitute for the interactive gate. Proceed. |
| "I'll draft the options and wait for them to wake up." | Waiting = the loop dies. Never defer a reversible choice to the human mid-loop; the only stop is the 08:00 time-gate. |
| "I should stop at the PR for human merge approval." | Attended mode stops at the PR; the loop does not. Merge it via `merge-pr` when green. |
| "This idea needs new tooling / a harness — that's interactive-session work, I'll skip it." | Heaviness isn't the boundary; reversibility is. Build the tooling on a branch — it's reversible. Only a hard-to-reverse step gets parked, and even then just that step, not the heavy work. |
| "Part of this would overwrite the dataset / touch production — I'll just do it." | That's the one thing you don't do unattended. Run a reversible variant (new path, local draft), park the irreversible step for an interactive session, continue. |
| "It's 08:00+ but I'll squeeze one more iteration." | Stop at the time-gate. Hand back a summary; the human resumes. |
| "The result is negative, the iteration failed — I should ask what to do." | A negative result is a real finding. Record the verdict, write/select the next step, continue. |

## Notes

- This skill **orchestrates** the existing skills — it does not replace them. Use `superpowers:brainstorming`, `superpowers:writing-plans`, `superpowers:subagent-driven-development`, `superpowers:systematic-debugging`, and `merge-pr` as the loop's steps; this skill only adds the autonomy discipline + the reversibility/judgment boundary + the iteration cadence + the closeout/next-step/time-gate rules.
- Follow all the repo's standing conventions (`.claude/rules/`): branch off `develop`, commit-message + co-author/reviewer trailers, the spec/plan locations, the iterations-history closeout entry, the open-topics convention, and the decisions-log convention. Unattended mode changes *who approves* (you, recorded), not *what gets produced*.
