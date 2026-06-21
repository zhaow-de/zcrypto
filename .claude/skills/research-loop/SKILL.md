---
name: research-loop
description: Use when the user asks to start the unattended / autonomous / overnight research loop (e.g. invokes /research-loop, "run research while I'm away", "keep iterating autonomously"). Runs full spec→plan→execute→verdict→merge research iterations with NO questions and NO waiting for input, toward the project's max-profitability research goal.
disable-model-invocation: false
---

# research-loop

## Overview

Run the project's research iterations **unattended** — the same brainstorm → spec → plan → subagent-driven execution → A/B verdict → merge cycle this repo has run for many iterations, but with **zero human interaction**. The human is away; nobody will answer. Your job is to keep the research moving autonomously and leave a reviewable trail.

**Overall goal (unchanged):** find a Qlib strategy / model / feature / data combination that maximizes profitability. Stay in the **research domain** — do NOT switch to live-trading or paper-trading preparation.

## The Iron Rule of autonomy

**Never stop to ask. Never wait for input. Never defer a choice to the human.** There is no human to respond — pausing means the loop dies.

When you hit ANY question or decision (a design fork, an ambiguity, an approval gate, a "which option" choice):

1. **List the options** (2-3) and their tradeoffs.
2. **Evaluate** them and **pick the most confident / most beneficial** one.
3. **Record** it as a paragraph in `.tmp/decisions.md` (gitignored), the question prefixed with `[iter-<NNN>]` (see format below).
4. **Continue** immediately with your pick.

This protocol **replaces** the repo's default "Rule 1: ask when unclear" *for the duration of the loop*. You still surface tradeoffs — but you surface them **into the decisions log**, then decide and proceed. The human reviews `.tmp/decisions.md` later and can correct course; that is the safety net, not a blocking question.

**There are exactly two ways the loop ends — nothing else is a stop:**
1. **The 09:00 Berlin time-gate** (step 10) — the normal end of an overnight run.
2. **A genuinely unrecoverable blocker** you cannot fix after real effort (e.g. the dataset is gone, the environment won't run). Even then: record what blocked you in `.tmp/decisions.md` before stopping.

Everything else that *feels* like a stopping point is NOT one — keep going:
- **An empty / exhausted open-topics backlog is NOT a stop** → manufacture the next work package (tweak knobs / try a different model — see Fallbacks).
- **A failed or negative-result iteration is NOT a stop** → record the verdict, pick the next thread, continue.
- **A mid-execution error is NOT a stop** → diagnose, fix, continue (step 6).
- **A decision/ambiguity is NOT a stop** → decide → record → continue (above).

**The approval gates are pre-satisfied.** Invoking the loop IS the human's standing approval. So:
- `superpowers:brainstorming`'s HARD-GATE (design approval before implementing) → satisfied by the recorded decisions + your spec self-review. Proceed to writing-plans without waiting.
- the spec user-review gate → satisfied; do your own self-review and move on.
- the executing-plans / subagent-driven-development handoff → just start; don't ask which mode.
- the PR merge → merge it yourself via `merge-pr` when green (do NOT stop at the PR for human approval, unlike attended mode).

## The loop (one iteration)

1. **Pick a work package.** Source it from the *Suggested next steps* of the **last iteration** (`docs/iterations-history.md`) or the **R&D open-topics** (`docs/open-topics/README.md`, the `## Research and development` Open/Partially-done lists). Keep it **small**: one hypothesis + a suggested validation approach, sized for a single iteration. If no feasible topic remains, **create one** by tweaking recipe knobs or trying a different model (see Fallbacks).
2. **Brainstorm** it with `superpowers:brainstorming` as a new iteration — autonomously (apply the Iron Rule to every question the skill would ask).
3. **Spec self-review** — run the brainstorming self-review; fix inline. (No user review gate — proceed.)
4. **Plan** with `superpowers:writing-plans`.
5. **Execute** with **`superpowers:subagent-driven-development`** (fresh-subagent-per-task + per-task review + final whole-branch review). *(The user's phrasing "executing-plans / subagents-driven execution" means this subagent-driven flow — what the project has used throughout.)*
6. **Handle issues mid-execution** — if something breaks (a failing test, a runtime error, a stale lock, a tooling gap), **diagnose and fix it, then continue**. Don't abandon the iteration; don't wait. Use `superpowers:systematic-debugging` for non-trivial failures.
7. **Closeout** — produce the **A/B verdict** (the iteration's measured result vs its baseline) and **suggest the next step** based on the result. Write the iterations-history entry.
8. **Capture follow-ups** — if multiple next steps surface, or you discover a better next step than the current backlog, or you spot a new tangent worth tracking, write them into `docs/open-topics/` (new `T<NNNN>` topic files + index, per `.claude/rules/open-topics.md`). In unattended mode the open-topics approval gate is pre-satisfied — create them, recording the rationale in `.tmp/decisions.md`.
9. **Merge** — when everything is green (tests pass, reviews clean), merge the PR with `merge-pr`.
10. **Time-gate** — check **Berlin time** (`TZ=Europe/Berlin date`). If it is **before 09:00**, start the **next** iteration (go to step 1). If it is **09:00 or later**, **stop and wait for the human** — post a concise summary of what landed and the proposed next step.

## `.tmp/decisions.md` format

Append one paragraph per decision (the file is gitignored). Example:

```markdown
[iter-023] How should the regime overlay set exposure off the BTC trend? (Decision: 1)
  1. **BTC vs 200d SMA, binary**
     Risk-on (full top-k) when BTCUSDT close > its 200-day SMA, else flat to cash/USDC. Canonical crypto regime filter, ~1 parameter (the window) → least overfit, strongest drawdown cut. Recommended.
  2. **BTC vs 200d SMA, graded**
     Full above the SMA, half within a ±band (chop), cash when below by a margin. Smoother / fewer all-cash whipsaws, but adds the band + half-size parameters.
  3. **Faster signal (100d / 50-200 cross)**
     100-day SMA, or a 50/200-day SMA cross. More responsive to regime turns, but more whipsaw and fee churn, and more parameters to overfit.
```

Prefix every entry with `[iter-<NNN>]`, and record each option with its explanation — laid out as fully as you would present them for a decision — plus the option you picked (the `(Decision: N)` marker) and a one-line why. You are not asking the human; you are leaving the same detail a question would carry, then deciding.

## Constraints & special cases

- **Research domain only.** Do not start live-trading or paper-trading prep (e.g. `T0006`, `T0013`) — those are out of scope for this loop.
- **qlib bug discovered?** Write an issue draft to `.tmp/qlib-bug-<subject>.md` using the template at `https://github.com/microsoft/qlib/blob/main/.github/ISSUE_TEMPLATE/bug-report.md`. A local qlib clone for reference/line-citations is at `/Users/zhaow/Projects/qlib`. Keep going by creating a workaround — don't block on it.
- **Out of feasible open topics?** Don't stop — manufacture the next work package: tweak a recipe's knobs (model hyperparameters, label horizon, universe, topk/holding, cost preset) or swap the model (e.g. a different GBDT config, linear, or another qlib model), forming a clean A/B vs the current best. Record the choice in `.tmp/decisions.md`.
- **Slow tasks** (multi-window re-measures, large fetches, full backtests): run them in the background and **check status about every hour** (a long fallback wakeup) rather than blocking — avoid endless waiting. When harness-tracked background work finishes you're re-invoked automatically.
- **Honesty holds.** Read verdicts on the cost-adjusted measures the project uses (e.g. paired cost-adjusted Sharpe, not gross ending_value — see `T0015`); a negative/null result is a valid, valuable outcome — record it and pick the next thread. Do not fabricate a positive result to keep the loop "successful."

## Red flags — you are about to violate autonomy

If you catch yourself doing any of these, STOP that impulse and apply the Iron Rule (decide → record → continue):

- Drafting a question / `AskUserQuestion` / "I'll ask the human"
- "This decision belongs to the human" / "I shouldn't pick unilaterally"
- "Rule 1 says ask when unclear"
- "I'll leave a note / draft and wait for them to wake up"
- "The brainstorming HARD-GATE / spec review / merge needs approval first"
- Stopping at the open PR instead of merging it
- Ending the turn while it is still before 09:00 Berlin with green work and a clear next step
- Treating an empty open-topics backlog as a "terminal condition" / reason to stop (manufacture a work package instead)
- Treating a failed iteration or a blocker as the end of the loop (fix it or pivot, then continue)

## Rationalizations — and the reality

| Rationalization | Reality |
|---|---|
| "This design choice belongs to the human." | In the loop you own every **reversible research** decision. Record it in `.tmp/decisions.md`; the human reviews and corrects later. That log IS their involvement. |
| "Rule 1 says surface tradeoffs and ask." | Rule 1's *ask* is suspended for the loop. You honor "surface tradeoffs" by listing+evaluating options in the decisions log, then deciding. Not deciding = the loop dies. |
| "The brainstorming HARD-GATE needs approval before I implement." | Invoking the loop is the standing approval. Your recorded decisions + spec self-review substitute for the interactive gate. Proceed. |
| "I'll draft the options and wait for them to wake up." | Waiting = the loop dies. Never defer to the human mid-loop; the only stop is the 09:00 time-gate. |
| "I should stop at the PR for human merge approval." | Attended mode stops at the PR; the loop does not. Merge it via `merge-pr` when green. |
| "It's 09:00+ but I'll squeeze one more iteration." | Stop at the time-gate. Hand back a summary; the human resumes. |
| "The result is negative, the iteration failed — I should ask what to do." | A negative result is a real finding. Record the verdict, write/select the next step, continue. |

## Notes

- This skill **orchestrates** the existing skills — it does not replace them. Use `superpowers:brainstorming`, `superpowers:writing-plans`, `superpowers:subagent-driven-development`, `superpowers:systematic-debugging`, and `merge-pr` as the loop's steps; this skill only adds the autonomy discipline + the iteration cadence + the closeout/next-step/time-gate rules.
- Follow all the repo's standing conventions (`.claude/rules/`): branch off `develop`, commit-message + co-author/reviewer trailers, the spec/plan locations, the iterations-history closeout entry, the open-topics convention. Unattended mode changes *who approves* (you, recorded), not *what gets produced*.
