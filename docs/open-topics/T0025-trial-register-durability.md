---
status: open
---

# Trial register durability + recomputable deflated Sharpe

## Context — what

The deflated-Sharpe multiple-testing defense deflates each candidate's Sharpe against a
pre-registered trial register (`runs/trials.jsonl`, written by `zcrypto stress` /
`rank` via `cli/experiment/trials.py`). That register lives in the **gitignored `runs/`
tree and lost its history** — it currently holds **4 entries** (the last `vol_target`
sweep) against **~46 distinct configs actually stress-tested** under `runs/stress/`. The
per-trial pooled daily return series is also never persisted (bundles store only
`stress_summary.json` aggregates + per-window delta CIs), so a deflated Sharpe cannot be
recomputed post-hoc with the correct cumulative trial count.

## Why this matters

The deflated Sharpe is the project's core false-discovery backstop — the Harvey-Liu-Zhu
`t > 3.0` multiple-testing hurdle the Phase-2 orientation pre-committed to
(`docs/research/03.phase2-orientation.md` §5.4). An undercounted register silently breaks
it: `deflated_sharpe` returns `NaN` when <2 trials are visible (`cli/experiment/stats.py`
`expected_max_sharpe`), and otherwise deflates against a near-empty, near-zero-variance
register — i.e. **no real penalty**. This directly hit the `momentum_tilt` verdict
(recorded `deflated_sharpe = NaN`; other recipes recorded artifactually-high 0.75–0.96
against the same degenerate register). The candidate's true multiple-testing standing was
never computable from the harness — it had to be reconstructed by hand from the saved
daily-delta bootstraps (pooled `t ≈ 1.3`, far short of the `t > 3` hurdle).

## Findings so far

- `runs/trials.jsonl` = 4 lines (`beta_null_vt40/45/55/60`, Sharpe ≈ 0.025, near-zero
  variance) vs ~46 distinct `runs/stress/*` bundles — the register was wiped with `runs/`.
- `register_trial` is only called by `zcrypto stress` and appends to the gitignored path
  (`cli/stress/command.py:155-164`); `rank` *reads* the register (`cumulative_sr_trials`)
  but never writes to it. `cumulative_sr_trials` dedups on `config_hash`
  (`cli/experiment/trials.py:49-76`).
- `deflated_sharpe(returns_best, sr_trials)` → `NaN` for <2 trials
  (`cli/experiment/stats.py:71-81`); the `momentum_tilt` bundle
  (`runs/stress/momentum_tilt/20260623T030034Z`) records `deflated_sharpe = NaN`, while
  other recipes record artifactually-high values (e.g. `k15` 0.96, `l60` 0.93, `vt60` 0.85)
  against the same tiny, near-zero-variance register.
- Bundles persist only annualized per-window aggregates + `delta_ci`; the per-period
  pooled daily series (the `returns_best` deflated Sharpe needs) is saved nowhere, so the
  metric is not recomputable offline.

## Suggested next steps

- Make the trial register **durable** — write it to (or mirror it into) a tracked,
  append-only location that survives `runs/` cleanup, rather than relying on gitignored
  `runs/trials.jsonl`.
- **Persist each trial's pooled daily return series** (or at least its per-period Sharpe)
  in the bundle, so deflated Sharpe is recomputable post-hoc against the true cumulative N.
- **Fail loud, not silent:** log/warn when `deflated_sharpe` is `NaN` or the register has
  <2 trials, so a broken/undercounted register surfaces at run time.
- Optional retro-fit: a one-shot rebuild that reconstructs the register from existing
  bundles where possible and recomputes deflated Sharpe across the Stage-2 candidates with
  the correct N — an honest multiple-testing read on the work already done.
