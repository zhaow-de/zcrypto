---
status: open
priority: high
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

## Suggested next steps

- Set LightGBM `seed` + `deterministic=True` + `num_threads=1` for reproducibility (slower); OR
- Average over N seeds (ensemble, or report holdout + CPCV as mean±std).
- Re-run the iter-13 feature comparison under determinism before claiming any feature edge.
- Consider reporting the holdout as a distribution, not a point estimate.
