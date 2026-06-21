# Label-horizon sweep (the prediction-target axis) — Design

**Iteration:** iter-28
**Advances open-topic:** `T0018` (OOS signal-generalization wall) — sweeps the last untested OHLCV-derived axis (the prediction target).
**Builds on:** the iter-22 `zcrypto stress` harness, the iter-25/26 feature-axis closure, the iter-27 model-axis closure.

## Context — what

Every result uses a **5-day label** (`Ref($close,-6)/Ref($close,-1)-1`). The OOS inversion (CPCV +1.0 → 2025 holdout negative) has been shown independent of the input features (iter-25/26) and the model class (iter-27). The one OHLCV-derived axis never swept is the **prediction target itself** — the forecast horizon. Does a shorter (1-day, mean-reversion-flavored) or longer (10/20-day, smoother/more regime-robust) horizon generalize OOS where 5-day inverts?

**Blocker (a real latent bug):** the stress harness hardcodes an 8-day purge (`windows.PURGE_DAYS`), leak-safe only for label horizons ≤ 8. A 10- or 20-day label would leak train→test in the OOS windows (the last train labels look forward into the test). So the purge must scale with the recipe's `label_horizon_days`.

## Why this matters

The prediction target is conceptually orthogonal to features (inputs) and model (fitter). If a different horizon's signal does not invert OOS, that is a genuine lead (gate it next). If every horizon inverts, the wall (T0018) is airtight across **inputs, fitter, and target** — making "the daily-OHLCV signal doesn't generalize to 2025+" conclusive and the on-chain frontier (T0010) the unambiguous next step. Either way the stress-harness purge fix is a correctness improvement that any future long-horizon experiment needs.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Fix the stress purge to scale with the recipe:** in `cli/stress/command.py`, pass `purge_days = max(PURGE_DAYS, recipe.label_horizon_days + 2)` to `build_oos_windows`. | Makes the train→test gap ≥ the label horizon for ANY recipe (leak-safe). For `label_horizon_days ≤ 6` (every existing recipe) it stays `max(8, ≤8) = 8` — **unchanged, no regression** to prior results; it only grows for the new long-horizon recipes. |
| 2 | **Three horizon recipes**, each `steady`'s book verbatim with only the label + `label_horizon_days` changed: `h1_steady` (1-day: `Ref($close,-2)/Ref($close,-1)-1`, horizon 2), `h10_steady` (10-day: `Ref($close,-11)/Ref($close,-1)-1`, horizon 11), `h20_steady` (20-day: `Ref($close,-21)/Ref($close,-1)-1`, horizon 21). `steady` (5-day) is the baseline. | Brackets the 5-day baseline with short (1d) and long (10/20d) to map the horizon→OOS curve. `label_horizon_days` MUST equal the max forward Ref (the leak-free-purge invariant in steady's own comment). |
| 3 | **A/B ungated on `zcrypto stress`** (`--seeds 8`): `steady` (5d) vs `h1_steady` / `h10_steady` / `h20_steady`. Read cost-adjusted Sharpe (`T0015`). | Tests whether any horizon avoids the OOS inversion before adding the gate. Gating a promising horizon is a follow-up, not this iteration. |

## Component file tree

```
cli/stress/
└── command.py    # MODIFY: purge_days = max(PURGE_DAYS, recipe.label_horizon_days + 2) passed to build_oos_windows
                  #         (import PURGE_DAYS from cli.stress.windows). Leak-safe for any label horizon.
cli/experiment/recipes/
├── h1_steady.py    # NEW: steady's book, label Ref($close,-2)/Ref($close,-1)-1, label_horizon_days=2.
├── h10_steady.py   # NEW: steady's book, label Ref($close,-11)/Ref($close,-1)-1, label_horizon_days=11.
└── h20_steady.py   # NEW: steady's book, label Ref($close,-21)/Ref($close,-1)-1, label_horizon_days=21.
tests/
├── test_stress_command.py    # EXTEND: a recipe with label_horizon_days=20 -> the windows' train_end is >= 20 days
│                            #         before test_start (purge scales); the default-horizon case still uses 8.
└── test_experiment_recipe.py # EXTEND: h1/h10/h20 resolve; label + label_horizon_days correct; rest of the book
                              #         matches steady (drift guard).
README.md                     # MODIFY: Usage — add h1_steady / h10_steady / h20_steady.
```

## A/B & verdict

Closeout (redis up): run `zcrypto stress` for `h1_steady`, `h10_steady`, `h20_steady` (`steady` 5d reused from disk). Per-window long-only Sharpe + mean / worst. Verdict → `docs/iterations-history.md`:
- Does any horizon **avoid the 2025 inversion** / beat `steady`'s 0.154 across windows? → a real lead (gate it next).
- If all horizons invert on 2025 → the wall is airtight across inputs/fitter/target; on-chain (T0010) is the unambiguous frontier.

## Scope & deferred

- **In:** the stress-purge fix (+ test); the 3 horizon recipes (+ drift tests); the ungated A/B + verdict; README.
- **Out:** gating a promising horizon (follow-up); horizons beyond {1,5,10,20}; on-chain data (T0010).
- **Untouched:** existing recipes' results (purge unchanged for horizon ≤ 6), the model/strategy/data layers.

## Closeout tasks (authored when the work is real)

- Run the 3 horizon recipes' stress; A/B vs `steady` → record the horizon→OOS verdict.
- iter-28 iterations-history entry (the purge fix + the horizon verdict); update `T0018` (target axis result — lead or wall-airtight).
- README `## Usage`: the 3 recipes.
