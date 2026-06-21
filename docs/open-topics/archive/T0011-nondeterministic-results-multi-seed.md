---
status: resolved
---

# Nondeterministic experiment results / multi-seed validation

## Context — what

LightGBM trains multi-threaded with no `seed`/`deterministic`/`num_threads` set. In the iter-13
validation, two runs of the *identical* `steady` recipe on the *same* data produced ending value
3,621 vs 4,817 (absolute holdout Sharpe −0.60 vs −0.37) — a ~33% / 0.23-Sharpe swing. `skeleton`
reproduced bit-for-bit (its top-5 book is robust to the tiny prediction jitter; `steady`'s top-10 +
`hold_thresh` is not).

## Why this matters

Single-run holdout point-estimates and the `rank` table / DSR / PBO surface are unreliable; every
prior single-run verdict (`steady`, `regime_steady`, and the iter-13 feature comparison) carries this
unquantified variance; a cross-asset "edge" cannot be separated from run noise.

## Findings so far

Confirmed via an iter-13 re-run. Likely cause: LightGBM multi-threaded float-reduction plus
bagging/feature subsampling (`subsample`/`colsample_bytree` < 1) with no fixed seed. The CPCV
path-Sharpe distribution (mean over folds) is steadier than the single holdout.

## Done so far

iter-14 (spec `00013`) shipped the multi-seed holdout distribution machinery and determinism support:

- `seed`/`deterministic` plumbing threaded through `cpcv._lgb_params` + the holdout `LGBModel`
  (`scaffold._seeded_model_config`); default `seed=None` preserves prior behavior byte-identical.
- `--deterministic` CLI flag: sets `seed=1` + `deterministic=True` + `force_row_wise=True` on every
  fit — reproducible and validated.
- `--seeds N` (default 1): runs the holdout N times with seeds 1…N; writes `holdout_seeds.json`
  (`per_seed` + `summary`). CPCV runs once; only the light `lgb.train` + `backtest()` path repeats.
- The **16-seed re-run** (2025-2026 holdout, light-`lgb.train` basis, after 12 bps fees) VINDICATED
  the concern — single-run rankings were largely seed-noise:

  | recipe | Sharpe mean±std | ending value mean | PSR mean |
  |---|---|---|---|
  | crossasset_steady | −0.426 ± 0.138 | ~4,507 | 0.266 |
  | skeleton | −0.510 ± 0.149 | ~4,329 | 0.228 |
  | alpha360_steady | −0.570 ± 0.171 | ~3,827 | 0.203 |
  | steady | −0.617 ± 0.207 | ~3,641 | 0.188 |

  True order inverts iter-13's single-run order: `steady`'s apparent #2 (ending 4,817) was a lucky
  seed — it is actually the worst by mean (−0.62) with the widest spread. `skeleton`'s apparent #3
  (3,664) was an unlucky seed — it is #2 and the most stable (±0.149). `crossasset_steady` has the
  best mean but only a modest separation from `skeleton` (z ≈ 0.6, within noise); only vs `steady`
  is the gap beyond the seed-noise band (z ≈ 1.1, modest). All four still lose (~−55% to −64%).
- Single-run holdout verdicts retired in favour of distributions for all future comparisons.

Residuals: CPCV stays single-seed (ensemble over CV folds already averages variance); prediction-ensemble
(seed-averaged signal) deferred to `T0012`.

## Suggested next steps

- _(none — resolved; see `T0012` for prediction-ensemble follow-up)_
