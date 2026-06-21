# Walk-forward OOS validation (the `stress` harness) — Design

**Iteration:** iter-22
**Advances open-topic:** `T0007` (multi-window stress harness) → **`partial`** at closeout — this lands the **OOS test-window walk-forward** (the validation use); the training-window-grid sub-scope stays parked (data-limited).
**Gates:** `T0016` (the first-class market-neutral L/S strategy) is gated on this iteration's verdict.
**Builds on:** iter-21 (`long_short_spread` + per-seed `ls_sharpe` in `run_holdout_seeds`), iter-14 (multi-seed holdout), iter-12 (walk-forward concept).

## Context — what

iter-21 showed a market-neutral long/short on the base cross-sectional alpha is profitable (`steady` L/S Sharpe +0.60, +33% net of costs over the 2025+ holdout) — the project's first positive backtest. **But that holdout (2025-01-01..2026-06-15) has been the dev test-segment since iter-9**, so the result carries selection-bias risk: the recipes' design/hyperparameters were evolved while watching that exact period. Before trusting the edge (or building the T0016 strategy), it must be validated **out-of-sample** — measured on test periods never tuned against.

The fix is **test-window** variation (a walk-forward): train only on prior data, test on a held-forward window, roll the window across history. (Training-window variation — T0007's original "2017 vs 2020 start" — does NOT address the selection-bias, and is infeasible anyway: the dataset starts 2020-01-01, no pre-2020 data.)

## Why this matters

A +33% market-neutral result in a −50% market is promising but unproven on one dev-seen window. If the L/S Sharpe is consistently positive across multiple OOS windows — *especially through the 2022 LUNA/FTX crisis* — the edge is credible and T0016 (the deployable strategy) is worth building. If it only works on 2025, it is overfit, and that is a critical finding that stops T0016. Either outcome is decisive.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Reuse `run_holdout_seeds` per OOS window** — for each test window, `dataclasses.replace(recipe, segments=…)` to a window-shifted recipe and call the iter-21 multi-seed holdout, which already returns per-seed `sharpe` (long-only) + `ls_sharpe` (market-neutral). | The window grid is the only new logic; the modeling/holdout/L/S evaluation is pure reuse (iter-12/14/21). No new modeling code, no retraining path. |
| 2 | **Window grid: annual OOS test windows 2022, 2023, 2024, 2025-26**, expanding-train from 2020-01-01, each trained **only on prior data** with a leak-safe **purge gap ≥ the label horizon** (`label_horizon_days`=6) between train-end and test-start. test 2025-26 = `2025-01-01..2026-06-15` (the data end) so it reproduces the iter-21 number as one of the four. | Annual windows span distinct regimes (2022 crash/crisis, 2023-24 recovery/bull, 2025 bear). The purge prevents the 5-day-ahead label from leaking train→test. Reproducing the 2025 cell anchors the comparison. |
| 3 | **A pure window builder** `build_oos_windows(test_starts, *, data_start, data_end, purge_days) -> list[dict]` (each `{"label", "train": (s,e), "valid": (s,e), "test": (s,e)}`), qlib-free + unit-tested. `valid` is set within the purge gap (ignored by the multi-seed light path, which reads only train+test) to keep the segments dict well-formed. | Isolates the leak-safe window math from the qlib-heavy harness; the only part with subtle correctness (purge, train-only-prior) is testable in isolation. |
| 4 | **A reusable `zcrypto stress --recipe <r> [--seeds N] [--data-dir] [--out]` subcommand** (`cli/stress/`): loops the window grid, runs `run_holdout_seeds` per window, prints a per-window summary table (long-only `sharpe` vs market-neutral `ls_sharpe`, medians), and writes `stress_summary.json` (per-window distributions + across-window aggregate). | The robustness harness T0007 always intended (a first-class, re-runnable command, not a one-off) — re-run as recipes evolve. Mirrors the existing single-command pattern (`rank`/`experiment`). |
| 5 | **Verdict = per-window L/S Sharpe + across-window consistency.** The edge is **validated** iff `ls_sharpe` is positive across the OOS windows (and survives the 2022 crisis window); if it's positive only on 2025, it is overfit and T0016 stays gated. | Directly answers the selection-bias question the iter-21 caveat raised. |

## Component file tree

```
cli/stress/
├── __init__.py        # NEW (package marker)
├── windows.py         # NEW: build_oos_windows(test_starts, *, data_start, data_end, purge_days) -> list[dict]
│                      #      (pure, leak-safe; train=[data_start .. test_start-purge], test=[test_start .. test_end]).
└── command.py         # NEW: stress(recipe_name, seeds, data_dir, out) — loop windows, dataclasses.replace segments,
                       #      run_holdout_seeds per window, per-window summary table + stress_summary.json.
cli/__main__.py        # MODIFY: register `from cli.stress.command import stress; app.command(name="stress")(stress)`.
tests/
├── test_stress_windows.py   # NEW: build_oos_windows — train-only-prior, purge gap ≥ purge_days, last window to data_end,
│                            #      label/segment shape; leak-safety (train_end strictly before test_start by ≥ purge).
└── test_stress_command.py   # NEW: stress loops the grid + aggregates (monkeypatch run_holdout_seeds → capture per-window
                             #      recipe.segments + assemble the summary; assert N windows, table, stress_summary.json).
README.md                    # MODIFY: Usage — the `zcrypto stress` subcommand.
```

## Window grid (concrete, purge = label horizon)

`build_oos_windows(test_starts=["2022-01-01","2023-01-01","2024-01-01","2025-01-01"], data_start="2020-01-01", data_end="2026-06-15", purge_days=8)` →

| label | train | test |
|---|---|---|
| oos_2022 | 2020-01-01 .. 2021-12-24 | 2022-01-01 .. 2022-12-31 |
| oos_2023 | 2020-01-01 .. 2022-12-24 | 2023-01-01 .. 2023-12-31 |
| oos_2024 | 2020-01-01 .. 2023-12-24 | 2024-01-01 .. 2024-12-31 |
| oos_2025 | 2020-01-01 .. 2024-12-24 | 2025-01-01 .. 2026-06-15 |

(train_end = test_start − `purge_days`; each test_end = the day before the next test_start, the last = `data_end`.)

## Verdict & A/B

Run `zcrypto stress --recipe steady` and `--recipe funding_steady` (`--seeds 8`). For each: the per-window OOS `ls_sharpe` (and long-only `sharpe`) distribution, plus the across-window summary (mean, min/worst-window, # windows positive). Verdict → `docs/iterations-history.md`:
- Is the **market-neutral L/S** Sharpe positive/consistent across the OOS windows (incl. 2022 crisis)? → validates or refutes the iter-21 edge.
- Does `funding_steady` differ from `steady` OOS? → confirms (OOS) the iter-21 finding that funding doesn't help market-neutral.

## Scope & deferred

- **In:** the pure window builder; the `zcrypto stress` subcommand (loops windows, reuses `run_holdout_seeds`, per-window summary + `stress_summary.json`); the OOS verdict; README; `T0007` → partial.
- **Out (parked):** the **training-window axis** (T0007's original "vary train start" — data-limited, no pre-2020 data; noted in T0007's remaining steps); the **continuous single-curve walk-forward** (one concatenated OOS equity curve — a possible later refinement); the **T0016** first-class L/S strategy (gated on this verdict).
- **Untouched:** the recipes, the modeling/holdout/L/S code (pure reuse), the data/cost layers.

## Closeout tasks (authored when the work is real)

- Run `zcrypto stress` for `steady` + `funding_steady` (`--seeds 8`, redis up) → record the per-window OOS `ls_sharpe` verdict (validated / overfit; crisis-window survival; funding OOS).
- Advance `T0007` → `partial`: `## Done so far` (the OOS walk-forward validation harness + verdict); trim `## Suggested next steps` to the parked training-window grid (gated on pre-2020 data).
- If the edge validates, note it green-lights `T0016`; if not, note T0016 stays gated and why.
- README `## Usage`: the `zcrypto stress` subcommand.
- iter-22 iterations-history entry (the stress harness + the OOS validation verdict).
