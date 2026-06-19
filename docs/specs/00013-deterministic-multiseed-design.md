# Deterministic experiments + multi-seed holdout distribution — Design

**Iteration:** iter-14
**Resolves open-topic:** `T0011` (nondeterministic experiment results / multi-seed validation).
**Defers:** prediction-ensemble → open-topic `T0012`.
**Depends on:** spec `00006` (skeleton), `00008` (CPCV), `00011` (walk-forward / the light `lgb.train`+`backtest` holdout path this reuses), `00012` (the iter-13 recipes being re-compared).

## Context — what

iter-13's validation exposed that the experiment is **nondeterministic**: two runs of the *identical* `steady` recipe on the *same* data produced ending value 3,621 vs 4,817 (absolute holdout Sharpe −0.60 vs −0.37). LightGBM trains multi-threaded with no `seed`/`deterministic` set, and the top-k book discretizes tiny per-model prediction jitter into materially different P&L. Consequently every single-run holdout verdict — iter-12's `steady`/`regime_steady` and iter-13's `crossasset_steady` "win" — carries unquantified run-to-run variance, and the cross-asset edge cannot be separated from noise.

iter-14 makes the recipe comparison trustworthy by reporting the holdout as a **distribution over N seeds** (not a single point), and adds opt-in bit-determinism for audit — then re-runs the iter-13 comparison to deliver an honest, variance-aware verdict.

## Why this matters

The project's whole decision loop (which recipe / feature set / strategy advances) rests on the holdout comparison. If a single holdout swings ~33% / 0.23-Sharpe run-to-run, no ranking is trustworthy. The fix that makes benchmarking *meaningful* is the **multi-seed distribution** (characterize the variance, compare distribution-vs-distribution). Bit-**determinism** is a separable concern (reproducibility for audit/debug), not required for the decision — so it is opt-in and the default/dev/test path never pays its cost.

## Goal

Report the holdout as a multi-seed distribution so the iter-13 comparison can be re-run and judged "is the cross-asset edge beyond the seed-noise band?", with opt-in determinism for reproducibility — all without slowing the default/dev/test path.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **`--seeds N`** (default 1) on `zcrypto experiment`: CPCV runs once; the **holdout** is fit N times at seeds `1…N` (varying LightGBM's bagging/feature RNG → distinct models); per-seed holdout metrics (ending value, absolute Sharpe, PSR, max-drawdown) aggregate into a distribution (mean ± std, min, max), written to the bundle as `holdout_seeds.json`. | The multi-seed distribution is what makes the comparison meaningful; it does NOT need determinism (distinct seeds + the natural multi-threaded jitter both sample the variance). |
| 2 | Per-seed holdout reuses the **light `lgb.train` + qlib `backtest()` path** (the cpcv/walk-forward helpers: `_lgb_params`, `_materialize_span`, `_split_xy`, `_rows_on`, the per-period backtest), NOT a fresh MLflow run per seed. The canonical MLflow bundle (positions/report) is produced once at the base seed. | A holdout is one fit; N of them via MLflow would be N heavy runs. The light path makes `--seeds 16` ≈ 2× a single experiment (CPCV-15 + holdout-16 fit-units). |
| 3 | **`--deterministic`** flag (default **off**): sets LightGBM `seed` + `deterministic=True` + `force_row_wise=True` on every fit (holdout via `model_config`, cpcv/walk-forward via `_lgb_params`). | Bit-reproducibility for audit/debug/exact-repro snapshots. Default off ⇒ the default path, all tests, `--quick`, and dev iteration stay fast (no ~2–4× determinism penalty). `deterministic=True` is reproducible while multi-threaded (needs `force_row_wise`, not `num_threads=1`). |
| 4 | A `seed` knob flows through `model_config.kwargs` (consumed by both `scaffold`'s `LGBModel` and `cpcv._lgb_params`); `--seeds N` sets the holdout seed sequence (`1…N`), and the CPCV + the canonical bundle use the first seed. | One flag, one plumbing point covers both fit sites. |
| 5 | **Comparison read:** a lightweight per-recipe distribution + a separation summary — e.g. is `crossasset_steady`'s holdout-Sharpe mean separated from `steady`'s by more than the pooled std ("edge beyond the seed band?"). | YAGNI: an aggregation + a stdout/summary, not a new statistics engine. `rank` is unchanged (cross-recipe DSR/PBO over single trials; the seed-distribution is a separate per-recipe artifact). |
| 6 | **Re-run (closeout):** the 4 iter-13 recipes (`skeleton`, `steady`, `alpha360_steady`, `crossasset_steady`) at `--seeds 16` (fast, no `--deterministic`) → holdout distributions → honest verdict. Flip `T0011` → `resolved`; supersede the iter-13 recipe-docstring single-run notes with the multi-seed verdict. | The fast sweep's conclusion is reproducible-in-conclusion (N=16 averaging); `--deterministic` remains available for an exact-repro run if ever needed. |
| 7 | **Scope:** holdout-only multi-seed; CPCV stays single-(deterministic-optional-)seed (its seed-sensitivity noted; multi-seed-CPCV deferred). Prediction-ensemble (averaging the N models into one signal) deferred → `T0012`. No strategy/feature changes. | The iter-13 anomaly + the verdict live in the holdout; characterizing it is the goal. Ensembling (variance *reduction*) is a separate production lever. |

## Component file tree

```
cli/experiment/
├── command.py        # MODIFY: add --seeds / --deterministic options to `experiment`
├── recipes/base.py   # (maybe) MODIFY: a model-config helper or no change — seed/deterministic injected at runtime, not stored per recipe
├── cpcv.py           # MODIFY: _lgb_params(recipe, *, seed, deterministic) injects seed/deterministic/force_row_wise into the lgb params
├── scaffold.py       # MODIFY: inject seed/deterministic into the holdout LGBModel build; orchestrate the multi-seed holdout + write holdout_seeds.json
├── walkforward.py    # (reuse) its light lgb.train+backtest holdout path is generalized/shared for the per-seed holdout
└── multiseed.py      # NEW (or a scaffold section): run_holdout_seeds(recipe, *, data_dir, seeds, deterministic) -> distribution; pure aggregation of per-seed metrics
tests/
├── test_multiseed.py            # NEW: pure aggregation (mean/std/min/max over per-seed metrics) + the separation read
├── test_experiment_command.py   # EXTEND: --seeds/--deterministic option wiring
├── test_experiment_cpcv.py      # EXTEND: _lgb_params injects seed/deterministic when asked; omits them by default
└── test_experiment_scaffold.py  # EXTEND (redis-gated): --seeds N writes holdout_seeds.json with N entries + an aggregate; determinism off by default
```

## Determinism mechanism

`--deterministic` ⇒ the lgb params gain `deterministic=True` + `force_row_wise=True` (RECON: confirm the exact LightGBM requirement — `deterministic` needs `force_row_wise` or `force_col_wise`; `num_threads` need not be 1). Off ⇒ neither is set (today's fast behavior). The `seed` (from the `--seeds` sequence) is always set (it controls the bagging RNG and is harmless without `deterministic`); only `deterministic`/`force_row_wise` are gated by the flag.

## Multi-seed holdout

`run_holdout_seeds(recipe, *, data_dir, seeds, deterministic)`: for each seed, materialize over the recipe's span, fit LightGBM (light path, that seed), backtest the test segment via qlib `backtest()`, compute the holdout metrics (ending value, absolute Sharpe, PSR, max-drawdown) — reusing the same metric definitions as the single-fit holdout (RECON: keep the light-path metrics consistent with `scaffold`'s `_extract_metrics` / `stats.psr` so the base-seed light metric ≈ the MLflow bundle metric). Aggregate to mean ± std / min / max → `holdout_seeds.json` (per-seed rows + the aggregate). CPCV runs once (the existing path). For `--seeds 1` (default) the behavior is the existing single holdout (no distribution overhead).

## Re-run & verdict

The 4 iter-13 recipes at `--seeds 16` (fast). Record, honestly: each recipe's holdout-metric distribution; whether `crossasset_steady`'s mean is separated from `steady`'s beyond the pooled std (edge real vs seed-noise); and whether `alpha360_steady` remains clearly worst. The verdict lands in the recipe docstrings (superseding the iter-13 single-run notes) and the iter-14 iterations-history entry. `T0011` → `resolved` (single-run verdicts are retired in favor of distributions).

## Cost (default stays fast)

| Scenario | Mode | Cost |
|---|---|---|
| Default / tests / `--quick` / dev | fast, `--seeds 1`, nondeterministic | 1× |
| Benchmark comparison | `--seeds 16` (fast) | ~2× a single run (holdout is the cheap part) |
| Audit / exact-repro | `+ --deterministic` | ~2–4× per fit, on top — opt-in only |

## Scope & deferred

- **In scope:** the `--seeds`/`--deterministic` options, the multi-seed holdout distribution + artifact, the comparison read, the re-run + verdict, and the docs/closeout (`T0011` resolved).
- **Deferred (open-topics):** prediction-ensemble (averaging the N models into one signal) → `T0012`; multi-seed CPCV → noted on `T0011`'s resolution / a future topic if warranted.
- **Untouched:** strategy / feature handlers / CPCV methodology / the data pipeline / the universe.

## Closeout tasks (authored when the work is real)

- Flip `T0011` → `resolved` (determinism + multi-seed shipped; single-run verdicts retired).
- README `## Usage`: document `--seeds` / `--deterministic` and `holdout_seeds.json`.
- The re-run + multi-seed verdict (recipe docstrings + iter-14 iterations-history entry).
