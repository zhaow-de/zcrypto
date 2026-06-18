# 00010 — Deflated Sharpe ratio, PBO, and a multi-recipe ranking surface

- **Date:** 2026-06-18
- **Status:** Approved design (pre-plan)
- **Iteration:** iter-11
- **Scope:** Resolve open-topic `00002` (validation rigor) by adding the
  **probabilistic / deflated Sharpe ratio** and the **probability of backtest
  overfitting (PBO)** on top of the CPCV machinery, plus an on-demand
  **`zcrypto rank`** command that treats each persisted run as a *trial* and
  applies DSR + PBO across them. All computed from the **existing daily-kline
  backtest outputs** — no new data.
- **Depends on:** spec `00008` (CPCV: the per-path Sharpe distribution + the run
  bundle / `cv_results.json`) and the iter-10 caveats mechanism
  (`cli/experiment/caveats.py`).
- **Resolves:** open-topic `00002` (flips `partial → resolved`), including its two
  *Interpretation caveats* (indicative band; holdout-vs-path regime mismatch).

## Goal

Turn the experiment harness from "produces a Sharpe distribution" into "tells you
whether that Sharpe is *real*": every run reports a **PSR** (probability the true
Sharpe > 0, corrected for sample length and non-normality), and a new
`zcrypto rank` command quantifies selection bias across the recipes you have
tried — the **deflated Sharpe** of the best trial (corrected for the number of
trials N) and the **PBO** (how often the in-sample-best trial is out-of-sample
overfit). This directly answers research §12's "testing 20 variants and picking
the best can turn a true Sharpe < 0.5 into an apparent 2.0."

## Background & constraints

- **No new data.** PSR/DSR/PBO are post-hoc statistics on the *return series and
  Sharpe ratios already produced* from daily klines; the ranking surface is
  bookkeeping over persisted runs. (The data-hungry validation concerns are
  separate topics: `00004` execution realism needs aggTrades; `00005`
  survivorship needs more daily klines.)
- **PBO/CSCV is inherently multi-trial** — it ranks multiple configs in-sample vs
  out-of-sample, so it needs each trial's daily return series over a common
  window. The run bundle does not currently persist a return series (only summary
  metrics + the CPCV path Sharpes), so this iteration persists a per-run
  `returns.csv`.
- **The ranking surface is on-demand and stateless** (user decision): a `rank`
  command scans `runs/`, treating each bundle as a trial — N is transparently the
  runs you kept; no separate registry.
- **Resolves the iter-10 interpretation caveats**: with PSR as the per-recipe
  significance measure and DSR/PBO as the cross-trial overfitting measures, the
  "indicative band" is replaced by a real probability and the
  holdout-vs-path comparison stops being presented as an overfit test.
- **Repo rules unchanged.** README `## Usage` (the `rank` command + PSR);
  `docs/iterations-history.md` closeout; `00002` → resolved; branch + PR into
  `develop`.

## Decisions (resolved during brainstorming)

| Fork | Decision |
| --- | --- |
| Scope | **Full `00002`** in one iteration: per-recipe PSR + the `rank` command (DSR + PBO). |
| Ranking surface | **On-demand `rank` scanning `runs/`** (stateless; N = bundles found); each run persists `returns.csv`. |
| **D1** Library | **Implement the formulas directly** (short, exact; fully testable). Do *not* add the heavy/aging MLFinLab dependency — use it only as a dev cross-check. |
| **D2** Cardinality | **PSR** = per-recipe (single-strategy significance). **DSR + PBO** = cross-recipe (in `rank`). |
| **D3** Return series | Persist `returns.csv` = the **holdout (test-window) cost-adjusted daily returns** per run; `rank` runs DSR + CSCV/PBO over the **common test window** across trials. |
| **D4** Caveats | DSR/PBO become the honest overfitting measures; the report's holdout marker is **relabelled a different-period reference** (not an overfit test). Both `00002` interpretation caveats are retired. |
| **D5** Command surface | A new **top-level `zcrypto rank`** (sibling to `experiment`) — not a restructure of `experiment` into `run`/`rank` subcommands. |

## Components

```
cli/experiment/
├── stats.py     # NEW: psr(), deflated_sharpe(), pbo_cscv() — pure, no qlib
├── rank.py      # NEW: scan runs/ → trials → DSR + PBO → ranked table + runs/rank.json
├── command.py   # MODIFY: compute PSR on the holdout returns; persist returns.csv; add psr to cv_results + stdout
└── report.py    # MODIFY: show PSR; relabel the holdout marker as a different-period reference
cli/__main__.py  # MODIFY: register `rank`
```

`cli/experiment/caveats.py` is **unchanged**: the two `00002` interpretation caveats live in
the `00002` doc, not in `EXPERIMENT_CAVEATS` (iter-10 surfaced only survivorship), so retiring
them is a doc-only closeout change (below).

## The statistics (`cli/experiment/stats.py`)

Pure functions on plain arrays/series; references are Bailey & López de Prado.
All Sharpe inputs are **per-period (non-annualized)** unless stated; the module
documents the unit contract.

- **`psr(returns, sr_benchmark=0.0) -> float`** — Probabilistic Sharpe Ratio:

  `PSR = Φ( (ŜR − SR*)·√(n−1) / √(1 − γ₃·ŜR + ((γ₄−1)/4)·ŜR²) )`

  where `ŜR` = sample Sharpe of `returns` (mean/std), `n` = len, `γ₃` = skew,
  `γ₄` = kurtosis (non-excess; normal = 3), `SR*` = `sr_benchmark`, `Φ` = normal
  CDF. Returns P(true SR > `sr_benchmark`).

- **`deflated_sharpe(sr_best, sr_trials, returns_best) -> float`** — Deflated
  Sharpe Ratio: `psr(returns_best, sr_benchmark=SR0)` where the benchmark is the
  expected maximum Sharpe under the null,

  `SR0 = √Var(sr_trials) · [ (1−γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)) ]`,

  `γ` = Euler–Mascheroni ≈ 0.5772, `N` = `len(sr_trials)`, `Var` over the trial
  Sharpes, `e` = Euler's number, `Φ⁻¹` = normal inverse-CDF. Returns P(the best
  trial's true SR > what N random trials would produce by luck).

- **`pbo_cscv(returns_matrix, n_splits=16) -> dict`** — Probability of Backtest
  Overfitting via Combinatorially-Symmetric Cross-Validation. `returns_matrix` =
  T×N (rows = aligned dates, cols = trials). Partition the T rows into `n_splits`
  (even) contiguous groups; for each of the `C(n_splits, n_splits/2)` ways to pick
  half as in-sample (complement out-of-sample): rank trials by IS Sharpe, take the
  IS-best, compute its OOS relative rank `ω̄ ∈ (0,1)`, logit `λ = ln(ω̄/(1−ω̄))`.
  Returns `{"pbo": mean(λ ≤ 0), "logits": [...]}` — PBO = fraction of splits where
  the IS-best is OOS-below-median. (Standard library uses `n_splits` even; the
  combinatorial count `C(16,8)=12870` is cheap.)

Edge cases (documented + tested): zero-variance returns → SR 0 / NaN-safe;
`N < 2` trials → DSR/PBO undefined (return NaN with a clear note); `n_splits`
larger than T → error.

## Per-recipe integration (`command.py`, `report.py`)

- After the holdout run, compute `holdout_psr = psr(holdout_returns)` where
  `holdout_returns = report_df["return"] - report_df["cost"]` (the cost-adjusted
  daily series, same basis as the existing absolute Sharpe).
- **Persist `returns.csv`** in the bundle: the holdout cost-adjusted daily returns
  (date, ret) — the input the `rank` command's CSCV/DSR consume.
- Add `"psr"` to the `holdout` block of `cv_results.json`; print a PSR line in the
  stdout summary; show PSR in the report.
- **Report (`report.py`):** keep the CPCV path-Sharpe histogram as a *descriptive
  dispersion* view (honestly labelled, no longer implied to be a CI), annotate the
  holdout marker as a **different-period (test-window) reference**, and show
  `PSR = …` in the panel. This is the concrete resolution of the two `00002`
  interpretation caveats.

## The `rank` command (`cli/experiment/rank.py`, `cli/__main__.py`)

`zcrypto rank [--out runs] [--n-splits 16]`:

1. Scan `runs/<recipe>/<ts>/` for bundles; each bundle with a `returns.csv` +
   `cv_results.json`/`metrics.json` is a **trial**. N = number of trials.
2. Align trials on the **intersection of their `returns.csv` dates** (warn if the
   windows differ materially — trials should share the test segment).
3. Build the T×N return matrix; per-trial Sharpe = sample Sharpe of its returns.
4. **DSR** for the best trial: `deflated_sharpe(sr_best, sr_trials, returns_best)`.
5. **PBO**: `pbo_cscv(matrix, n_splits)`.
6. Print a ranked table (recipe/run, Sharpe, PSR, rank) headed by `N trials`,
   `DSR(best) = …`, `PBO = …`; write `runs/rank.json` (the matrix metadata,
   per-trial Sharpe/PSR, DSR, PBO, the alignment window).
7. **JSONL log events**: `rank-scan` (n trials), `rank-aligned` (window, T),
   `rank-done` (dsr, pbo).

Degenerate cases: 0 trials → actionable error; 1 trial → rank the single trial,
report DSR/PBO as N/A with a note (need ≥2 for cross-trial deflation).

## Artifacts

- **`cv_results.json`** `holdout` block gains `"psr"`.
- **`returns.csv`** (new, per bundle): `date,ret` — holdout cost-adjusted daily returns.
- **`runs/rank.json`** (new): `{n_trials, window:[from,to,T], n_splits, trials:[{recipe, run, sharpe, psr}], dsr_best, pbo}`.

## Testing strategy

- **`tests/test_experiment_stats.py`** (pure, no qlib): `psr` against a
  hand-computed normal-returns case (skew 0, kurtosis 3 reduces to the textbook
  PSR) and a known-PSR fixture; `deflated_sharpe` monotonic in N (more trials →
  lower DSR) and reduces to PSR-vs-SR0; `pbo_cscv` returns ≈0 for N identical
  good strategies, ≈high for noise-fit strategies (a constructed overfit matrix);
  edge cases (zero variance, N<2, n_splits>T).
- **`tests/test_experiment_rank.py`** (no qlib): build 2–3 synthetic bundles
  (each a dir with `returns.csv` + minimal `cv_results.json`), run the `rank`
  CliRunner invocation, assert the ranked table, `runs/rank.json` shape, and
  DSR/PBO present; assert the 0-trial and 1-trial degenerate paths.
- **`tests/test_experiment_command.py`** (redis-gated, extend): a run writes
  `returns.csv` and `cv_results.json.holdout.psr`; stdout shows the PSR line
  (`--quick` is sufficient — PSR is on the holdout, computed in both modes).
- **`tests/test_experiment_report.py`**: PSR text present; holdout marker carries
  the different-period label.

## Out of scope

- Execution realism / slippage (`00004`); survivorship / PIT universe (`00005`);
  the BTC-regime overlay (`00003`). DSR/PBO improve in *power* with more
  history/instruments but do not require it.
- A persistent trials registry (the on-demand scan was chosen); MLFinLab as a
  runtime dependency.

## Closeout (executed at end of iteration, per the rules)

- README `## Usage` — document `zcrypto rank` and the per-run PSR.
- `docs/open-topics/00002-validation-rigor.md` — flip `status: partial →
  resolved`; add a `## Resolution` note (PSR per-recipe, DSR + PBO via `rank`,
  caveats retired); move its bullet to `## Resolved` in
  `docs/open-topics/README.md`.
- `docs/iterations-history.md` — the iter-11 entry.

## References

- Open-topic: `docs/open-topics/00002-validation-rigor.md`.
- Bailey & López de Prado (2012), *The Sharpe Ratio Efficient Frontier* (PSR);
  (2014) *The Deflated Sharpe Ratio*; Bailey, Borwein, López de Prado, Zhu
  (2015), *The Probability of Backtest Overfitting* (CSCV).
- Research roadmap: `docs/research/01.binance-eea-spot-quant.md` §12, §13 Stage 3.
- Prereq: spec `00008` (CPCV).
