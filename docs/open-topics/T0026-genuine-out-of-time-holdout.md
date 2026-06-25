---
status: open
---

# Genuine out-of-time holdout (the reserved-holdout governance gap)

## Context — what

The Phase-2 orientation's validation design called for a *reserved true holdout* — data walled
off from the search, spent only a budgeted number of times
(`docs/research/03.phase2-orientation.md` §5.5; spec `00032` holdout-look governance). In
practice no such walled-off dataset exists. The recipe `test` segment (2025-01-01 →
2026-06-15) is the **same period** as the `zcrypto stress` `oos_2025` window, which every
stress run evaluated throughout the Stage-2 search. So the "reserved-holdout look" was never
operational: the 2025+ data is effectively in-sample.

## Why this matters

Without a genuinely-unseen holdout (or forward out-of-time data), no in-sample candidate can be
*independently* confirmed — the harness can map robustness but cannot defeat
overfitting / multiple-testing for real. This is the partner gap to `T0025`: T0025 is "count the
trials honestly," T0026 is "reserve the data honestly." Together they are the gate for ever
promoting a candidate (momentum or any future signal) from "in-sample signal" to "confirmed
edge." The `momentum_tilt` episode is the concrete cost: its +0.200 already includes the
`oos_2025` window, so there was no clean test left to spend.

## Findings so far

- `_TEST_STARTS` includes `2025-01-01` (`cli/stress/command.py:17`); the `oos_2025` window's
  test span ≈ 2025-01-01 → `data_end` (~2026-06-18) coincides with the recipe `test` segment
  (`cli/experiment/recipes/*.py`).
- `momentum_tilt`'s +0.200 is the mean of four stress windows including `oos_2025` (+0.164) —
  i.e. the "holdout" period was in-sample the whole time.
- The orientation/spec describe the intended reserve, but it was implemented as a normal
  walk-forward window, not a walled-off holdout.
- The dataset ends ~2026-06-15; only days of genuinely-new data have accrued since — too short
  for a Sharpe today, but the basis for forward validation going forward.

## Suggested next steps

- Define and **freeze a genuinely-reserved holdout** that no search/A-B touches — either a
  future-dated out-of-time window or a strict carve-out never fed to `stress`/`experiment`
  during the search — with an explicit budgeted-looks discipline.
- Stand up **forward-walk / out-of-time validation** as new data accrues (ties to `T0006`
  paper-trading) — the only pristine test available now.
- Pair with `T0025` so "count the trials" + "reserve the data" together make the
  multiple-testing defense real *before* any candidate is promoted.
