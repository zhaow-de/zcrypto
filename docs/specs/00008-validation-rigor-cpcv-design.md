# 00008 — Validation rigor: purged k-fold + embargo → CPCV for `zcrypto experiment`

- **Date:** 2026-06-17
- **Status:** Approved design (pre-plan)
- **Iteration:** iter-9
- **Scope:** Replace the experiment harness's single chronological evaluation
  with **combinatorial purged cross-validation (CPCV)** as the *default* run:
  many purged + embargoed splits are stitched into multiple backtest **paths**,
  yielding a per-recipe **distribution** of out-of-sample Sharpe / return /
  max-DD (+ rank-IC), while the existing `test` window is reserved as an
  untouched final **holdout**. A `--quick` flag opts back into today's fast
  single run. Implements roadmap §13 **Stage 2** (purged k-fold + embargo) and
  enters **Stage 3** (CPCV); the **deflated Sharpe ratio** and the multi-recipe
  ranking surface it needs are explicitly **deferred**.
- **Depends on:** spec `00006` (experiment skeleton — the single-split harness
  this upgrades) and spec `00007` (config — `--data-dir` / `[zcrypto].data_dir`).

## Goal

`zcrypto experiment --recipe <name>` becomes rigorous by default: it runs CPCV
over `train+valid`, reporting how a recipe's out-of-sample Sharpe is
*distributed* across many leakage-free backtest paths (mean / std / **worst
path**) — so an apparently-good recipe whose edge is one lucky path is visible at
a glance — then reports the honest final estimate on the untouched `test`
holdout. `--quick` preserves the fast single-run iteration loop.

## Background & constraints

- **The leakage this fixes.** Spec `00006` shipped a single chronological
  `train (2020–23) / valid (2024) / test (2025–26)` split deliberately, *flagging
  but not fixing* its leakage: the Alpha158 label
  `Ref($close,-2)/Ref($close,-1)-1` is a forward return overlapping its
  neighbors, so the last rows of `train` leak into `valid` and of `valid` into
  `test`. Purging + embargo removes exactly those overlapping rows around every
  fold boundary.
- **Why a distribution, not a point.** Research §6/§12/§13 (López de Prado,
  Ch. 7 & 12) names backtest overfitting *the* primary killer of retail ML
  strategies. One train/test split gives one Sharpe with no sense of its
  variance; CPCV produces many out-of-sample paths, exposing the spread. This is
  the §13 Stage 2 → Stage 3 upgrade.
- **The deferral cut.** The **deflated Sharpe ratio** (and PBO) are *statistics
  computed from* the CPCV path distribution; they correct an observed Sharpe for
  the number of trials. They — and the multi-recipe comparison / ranking surface
  that "number of trials" bookkeeping requires — are deferred. This iteration
  builds the *engine* (the distribution); a later one adds the *consumer*. See
  *Out of scope*.
- **Compute.** CPCV `N=6, k=2` ⇒ C(6,2)=**15** model trains + **5** path
  backtests + the holdout train/backtest — order **minutes** at daily scale
  (~20 instruments × ~5y × 158 features). Accepted as the default cost; `--quick`
  is the escape hatch.
- **Reuse, don't rebuild.** qlib's `DatasetH` segment is a single contiguous
  `(start,end)` tuple and **cannot express a non-contiguous CPCV train set**, so
  the CPCV loop materializes the feature/label matrix once via the qlib handler,
  then does split/fit/predict in pandas and drives the backtest through qlib's
  signal-based `backtest()` API. The single-split holdout reuses today's
  `run_experiment` unchanged.
- **Repo rules unchanged.** README `## Usage` updated in the same change;
  `docs/iterations-history.md` closeout; this iteration also enhances the
  open-topics convention and transitions topic `00002` to *partially done* at
  closeout (see *Closeout*).

## Decisions (resolved during brainstorming)

| Fork | Decision |
| --- | --- |
| Scope cut | **Purged k-fold + embargo → CPCV** this iteration; **deflated Sharpe + PBO**, the multi-recipe ranking/N-trials surface, and the MLFinLab dependency are **deferred** (CPCV is the engine; deflated Sharpe is a later consumer). |
| CV output | **Per-path portfolio Sharpe / ann.return / max-DD distribution (+ rank-IC)** over `train+valid`; the `test` window is **never touched by CV** and stays a single untouched final holdout. Evaluates the recipe's **fixed** configuration (no hyperparameter search). |
| CLI surface | **CPCV is the default**; `--quick` opts back into today's single train→backtest run. |
| **A** Holdout step | The final holdout is **byte-for-byte today's `run_experiment`** (train→valid early-stop→backtest `test`). CPCV is layered *before* it over `train+valid`; `--quick` runs *only* this step. |
| **B** CPCV size | Defaults **`N=6` groups, `k=2` test groups** → 15 splits, **5 paths**, recipe-configurable; bump `N` for a richer distribution at linear compute cost. |
| **C** Purge / embargo | Derived from two new recipe fields **`label_horizon_days=2`** (leading-edge label purge) and **`feature_lookback_days=60`** (trailing-edge feature embargo) — two precise channels, not one fat symmetric gap. |
| **D** Fold early-stopping | **Disabled inside CPCV folds** (fixed `num_boost_round` = the recipe's value) for a deterministic per-fold estimate; the holdout keeps early stopping on `valid`. |
| **E** Report | **Append a 4th panel** (path-Sharpe histogram + holdout marker) to the existing `report.html`, not a separate file. |

## Package layout

```
cli/experiment/
├── command.py          # MODIFY: default = CPCV → holdout; add --quick; CV stdout line + cv_results.json
├── scaffold.py         # MODIFY: extract a shared exchange/strategy/fee config builder; holdout flow unchanged
├── cv.py               # NEW: PURE split math (groups, C(N,k) combinations, purge, embargo, path assembly) — no qlib
├── cpcv.py             # NEW: qlib orchestration (materialize once → per-split fit/predict → assemble paths → per-path backtest → aggregate)
├── report.py           # MODIFY: append the 4th CV-distribution panel
└── recipes/base.py     # MODIFY: add 4 CV fields to the Recipe dataclass (defaults preserve current behavior)
```

`skeleton.py` inherits the new field defaults — no edit needed unless overriding.

## The CV engine — `cli/experiment/cv.py` (pure, no qlib)

Fully unit-testable split math, isolated from qlib.

- **Groups.** Partition the ordered unique calendar of the materialized matrix
  (over `train+valid`) into **N contiguous groups** of ~equal date count.
- **Splits.** For each of the **C(N, k)** combinations choosing k groups as the
  test set, the remaining N−k groups form the train set, then for **each maximal
  contiguous test block `[t0, t1]`**:
  - **Purge** (leading edge): drop train rows with date `d ∈ [t0 − label_horizon_days, t0 − 1]` — their forward label window reaches into the block.
  - **Embargo** (trailing edge): drop train rows with date `d ∈ [t1 + 1, t1 + feature_lookback_days]` — their backward feature window reaches into the block.
- **Paths.** Number of backtest paths **φ = C(N−1, k−1)** (= k·C(N,k)/N). Each
  group is a test group in exactly φ splits; **path j** takes, for every group,
  that group's j-th test-prediction — stitched in calendar order into one
  full-`train+valid`-span prediction series. For `N=6, k=2`: 15 splits, **5
  paths**.

Proposed shapes (finalized in the plan):

```python
@dataclass(frozen=True)
class CVSplit:
    test_dates: list           # the k test groups' dates, in calendar order
    train_dates: list          # remaining groups MINUS purged + embargoed rows

@dataclass(frozen=True)
class CVPlan:
    n_groups: int
    test_groups: int
    purge_days: int
    embargo_days: int
    splits: list               # length C(N, k)
    n_paths: int               # C(N-1, k-1)

def build_cv_plan(calendar: list, *, n_groups: int, test_groups: int,
                  purge_days: int, embargo_days: int) -> CVPlan: ...

def assemble_paths(plan: CVPlan, predictions: dict) -> list:
    """predictions: {split_index -> pred DataFrame on that split's test dates};
    returns φ full-span prediction series (one per path)."""
```

## qlib integration — `cli/experiment/cpcv.py` (orchestration)

1. **Materialize once.** Build the Alpha158 feature+label matrix for the
   universe over `train+valid` via the qlib handler → one DataFrame indexed by
   `(datetime, instrument)` (keeps the disk-cache win from spec `00006`).
2. **Per split (×15).** Slice train/test rows in pandas by date membership; fit
   the recipe's `LGBModel` with **early stopping disabled** and a fixed
   `num_boost_round`; predict the held-out rows. One train per split; predictions
   are reused across paths.
3. **Assemble φ paths** via `cv.assemble_paths`.
4. **Per path (×5).** Feed the stitched prediction series to
   `TopkDropoutStrategy(signal=…)` through qlib's signal-driven
   `qlib.backtest.backtest(...)` (no recorder) using the **shared** exchange/fee
   config (extracted from `scaffold._port_analysis_config`) → daily return series.
5. **Per-path metrics** = `risk_analysis` on the path's **absolute**
   (cost-adjusted) daily returns; the path **"Sharpe"** is that
   `information_ratio` (rf = 0), matching the existing `strategy_absolute` metric
   in `scaffold._extract_metrics`. Also compute **rank-IC** per split (Spearman
   of prediction vs. realized label on test rows).
6. **Aggregate** into the distribution + rank-IC stats; return to `command.py`.

`cv.py` stays pure; all qlib calls live in `cpcv.py`. The holdout run remains
`scaffold.run_experiment` exactly as today.

## Recipe additions (`recipes/base.py`)

Four new fields with behavior-preserving defaults (existing call sites unaffected):

```python
label_horizon_days: int = 2       # leading-edge purge depth (Alpha158 default label)
feature_lookback_days: int = 60   # trailing-edge embargo depth (Alpha158 longest window)
cv_n_groups: int = 6              # CPCV groups (N)
cv_test_groups: int = 2           # CPCV test groups per split (k)
```

## Output / run bundle

The default run produces today's holdout bundle **plus** `cv_results.json`:

```jsonc
{
  "cv": { "method": "CPCV", "n_groups": 6, "test_groups": 2,
          "n_splits": 15, "n_paths": 5,
          "purge_days": 2, "embargo_days": 60,
          "span": ["2020-01-01", "2024-12-31"] },
  "paths": [ { "path": 0, "sharpe": .., "annualized_return": ..,
               "max_drawdown": .. }, ... ],
  "distribution": { "sharpe_mean": .., "sharpe_std": .., "sharpe_median": ..,
                    "sharpe_worst": .. },
  "rank_ic": { "mean": .., "std": .., "ir": .. },
  "holdout": { "sharpe": .., "annualized_return": .., "max_drawdown": ..,
               "information_ratio": .., "ending_value": .. }
}
```

`sharpe` everywhere = `risk_analysis` `information_ratio` on **absolute** (rf = 0)
returns (per *qlib integration* step 5); `sharpe_worst` is the minimum path
Sharpe. The `holdout` object additionally carries `information_ratio` = the
existing **excess-return-vs-benchmark** IR headline (distinct from its absolute
`sharpe`), preserving continuity with spec `00006`'s metrics.

- **Report (E):** a 4th panel appended to `report.html` — a histogram/box of the
  φ path Sharpes with the holdout Sharpe drawn as a vertical line; title shows
  mean ± std and worst path. Holdout far above the path cloud = overfitting cue.
- **Stdout:** today's holdout headline + metrics, plus one line:
  `CPCV (5 paths, train+valid): Sharpe 0.70 ± 0.30 (worst 0.20) · rank-IC 0.04`.
- `model.pkl` = the **holdout** model (the predict-ready artifact); the 15 fold
  models are transient.
- **`--quick`:** skips steps 1–4 entirely; output is byte-for-byte today's
  single-run bundle (no `cv_results.json`, 3-panel report, no CPCV stdout line).

## CLI surface

```
zcrypto experiment [--recipe skeleton] [--data-dir <dir>] [--out runs] \
                   [--quick] [--open/--no-open] [--svg/--no-svg] [--refresh-cache]
```

`--quick` is the only new flag. Global `--log` / `--log-level` apply.

## Error handling & logging

- Unchanged paths: unknown `--recipe`, missing/invalid `--data-dir` (per specs
  `00006`/`00007`).
- A degenerate CV config (e.g. `cv_test_groups ≥ cv_n_groups`, or a group too
  short to survive purge+embargo) → actionable error before any training.
- **JSONL events** (existing `cli/logging`): `cpcv-start` (N, k, splits, paths),
  `split-trained` (index), `paths-assembled` (φ), `path-backtest` (index,
  sharpe), `cv-aggregated` (distribution), alongside the existing holdout events.

## Testing strategy

- **Pure unit tests** (`tests/test_cv.py`, fast, no qlib): `n_splits == C(N,k)`;
  `n_paths == C(N−1,k−1)`; for every split, **no train date** falls in any test
  block's `[t0 − purge, t1 + embargo]`; path assembly yields φ paths, each
  covering every date exactly once with each date sourced from a split where its
  group was held out.
- **Integration (scaled)**: extend the synthetic fixture and run the **default**
  path with a small CV config (e.g. `N=4, k=2` → 6 splits, 3 paths) sized so each
  group exceeds the embargo + Alpha158 warmup (the test recipe may shrink
  `feature_lookback_days`); assert `cv_results.json` shape, the 4th panel
  renders, and the holdout bundle is still produced.
- **`--quick` parity**: asserts the single-run outputs match today's (no
  `cv_results.json`, 3-panel report, same `metrics.json` shape).
- **Suite speed**: the existing experiment tests that only exercise the single
  run move to `--quick` so the suite stays fast under "CPCV by default".
- **Manual**: run the default on real `./data`; open `report.html`; sanity-check
  the path distribution vs. the holdout marker.

## Out of scope (deferred → open-topic `00002`)

- **Deflated Sharpe ratio + PBO** (probability of backtest overfitting) computed
  on top of the CPCV path distribution.
- The **multi-recipe comparison / ranking surface** that deflated Sharpe needs
  (tracking the number of trials N across recipe runs) — the reason this slice
  was cut.
- **Hudson & Thames MLFinLab** as a reference-implementation dependency.

`00002` stays **open** until the closeout below transitions it to *partially
done* (it is not closed — the deferred items remain).

## Closeout (repo conventions — executed at end of iteration, after CPCV lands)

- **Open-topics rule enhancement** (`.claude/rules/open-topics.md`): introduce a
  `partial` status, a `## Partially done` index section, and the
  partial-completion lifecycle + index-sync wording.
- **`00002` partial-transition**: flip `status: open → partial`, add a truthful
  `## Done so far` (with this spec + the merged PR links), trim
  `## Suggested next steps` to the deferred remainder, and move its index bullet
  from `## Open` to `## Partially done`.
- **README `## Usage`**: document `--quick` and the CPCV output.
- **`docs/iterations-history.md`**: append the iter-9 entry.

## References

- Prerequisites: spec `00006` (experiment skeleton), spec `00007` (config).
- Research roadmap: `docs/research/01.binance-eea-spot-quant.md` §6 (purged
  k-fold + embargo), §12 (overfitting), §13 Stage 2–3.
- Open topic: `docs/open-topics/00002-validation-rigor.md`.
- López de Prado, *Advances in Financial Machine Learning*, Ch. 7 (purged k-fold
  + embargo) & Ch. 12 (CPCV, backtest paths).
- qlib: `qlib.backtest.backtest`, `TopkDropoutStrategy`, `risk_analysis`.
