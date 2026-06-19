# Pluggable feature handler + richer-signal experiment — Design

**Iteration:** iter-13
**Advances open-topic:** `T0008` (pluggable feature handler) — flipped to `partial`/`resolved` at closeout.
**Depends on:** spec `00006` (experiment skeleton — the Alpha158 baseline), spec `00008` (CPCV / purge-embargo validation), spec `00011` (the iter-12 strategy seam this mirrors).

## Context — what

After iter-12, the experiment scaffold is fully built and rigorously validated (CPCV, PSR, DSR, PBO, `rank`), and three recipes have been measured on current data: `skeleton`, `steady`, and `regime_steady`. **All three fail the roadmap's Stage-2 profitability gate** (research §13: net OOS Sharpe > 0.7, max-drawdown < 35%): each posts a *negative* 2025-2026 holdout Sharpe and loses ~63-66%, with CPCV OOS Sharpe ~+1.0 on 2020-2024 inverting to negative on the holdout and PBO 0.91-0.99. Recipe tuning (`steady`) and the Stage-3 regime overlay + walk-forward (`regime_steady`) did not rescue it.

The roadmap's own decision rule (§13, "Thresholds that change the plan") is therefore triggered: at sub-0.3 — here negative — OOS Sharpe after Stage-3 attempts, the bottleneck is the **signal / strategy family, not the harness**. The harness is sound; the daily Alpha158/LGBM cross-sectional ranker has no edge those levers can rescue.

This iteration attacks the signal. The scaffold hardcodes `Alpha158` as the feature handler in both `scaffold.py` and `cpcv.py`. iter-13 makes the handler **recipe-pluggable** (the symmetric twin of iter-12's pluggable strategy seam) and uses it to test whether a **richer or structurally-different feature set** carries an edge the per-instrument Alpha158 ranker lacks — measured under the same validation rigor against the `skeleton`/`steady` benchmarks.

## Why this matters

This is the cleanest "does an edge exist here at all?" experiment. Alpha158 and Alpha360 are both **per-instrument** OHLCV feature sets — they encode each coin's own price/volume history and have **no cross-asset structure**. Research §5/§14 single out the genuinely-additive crypto edges as cross-asset: relative strength vs BTC, BTC→alt lead-lag, and cointegration deviation. If feeding the ranker that missing information still does not clear a meaningful bar, that is a real, decision-driving finding (per §13: the next fork becomes pivot-family or treat the year as an education expense). Either outcome advances the project honestly.

## Goal

Make the feature handler a recipe-selectable seam, ship two new feature sets (the built-in `Alpha360` and a custom cross-asset handler), and run a clean A/B of both against the benchmarks — recording the honest verdict on whether richer features carry edge.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | `Recipe.feature_config = {class, module_path}` (handler class only); the existing `handler_kwargs` keeps the processors + label. A `scaffold.handler_config(feature_config, instruments, segments, handler_kwargs)` helper builds the full qlib handler config, used in **both** `scaffold.py` and `cpcv.py:_materialize_span`. | Mirrors iter-12's `strategy_config` + `strategy_config_with_signal` seam exactly; minimal surface; the class is the only thing varying across feature sets. |
| 2 | `skeleton`/`steady`/`regime_steady` migrate behavior-preservingly to `feature_config = {Alpha158}`; a regression test asserts the built handler config is unchanged. | Benchmark preservation — same guarantee as the iter-12 strategy migration. |
| 3 | Feature set (a): qlib built-in `Alpha360` via a one-line `feature_config` swap. | Exercises the seam end-to-end; a cheap data point. Honest expectation: same per-instrument OHLCV information, more dimensions → more overfit, not more edge. |
| 4 | Feature set (b): a custom cross-asset handler = Alpha158 features + a `CrossAssetProcessor` that appends BTC-anchored cross-asset features (relative strength, rolling beta, lead-lag, cointegration-deviation) and cross-sectional rank features. | Adds the information Alpha158/360 structurally lack; the real "different information" test. |
| 5 | Cross-asset implementation = **Approach A (post-load processor)**: a qlib `Processor` receives the full panel (all instruments incl. BTCUSDT), computes the cross-asset columns in pure pandas (a unit-testable function), and appends them. | Reuses Alpha158 + qlib's processor framework; the math is an isolated pure function; leak-free by construction (all trailing windows; cross-sectional rank is contemporaneous). Rejected: a bespoke `StaticDataLoader` (more code, diverges from the handler pattern) and cross-instrument expression operators (qlib's stock engine doesn't support them cleanly — fragile). |
| 6 | Cross-asset feature families (curated, YAGNI): relative strength vs BTC (5/20d), rolling beta to BTC (20/60d), BTC lead-lag (coin return on BTC's 1-3d lagged return), cointegration-deviation (rolling z-score of the log-coin ~ log-BTC residual), cross-sectional rank of momentum & realized-vol across the universe. BTC is the anchor (crypto's dominant factor, already in the universe). | A focused, defensible set of the additive edges named in research §5/§14 — not an exhaustive feature zoo. |
| 7 | Experiment design: hold **`steady`'s book/model/label/segments/fees constant** and vary ONLY the feature handler. Two demo recipes: `alpha360_steady` and `crossasset_steady`. | Clean A/B — any difference is attributable to features. `steady`'s lower turnover lets a real feature edge show through the cost noise that buried `skeleton`. |
| 8 | Validation at closeout: run `crossasset_steady`, `alpha360_steady`, `steady`, `skeleton` through full CPCV + `zcrypto rank`; record the honest verdict in the recipe docstrings + iterations-history. | Same discipline as iter-12; either outcome is a real result. |
| 9 | OHLCV-only this iteration. Funding-rate / on-chain / order-book features (which need a new data source) are deferred to a **new open-topic**, opened at closeout. | YAGNI; bounds the iteration to our daily-kline data. |

## Component file tree

```
cli/experiment/
├── recipes/base.py            # MODIFY: add Recipe.feature_config; default points at Alpha158
├── recipes/skeleton.py        # MODIFY: add feature_config={Alpha158} (behavior-preserving)
├── recipes/steady.py          # MODIFY: same
├── recipes/regime_steady.py   # MODIFY: same
├── recipes/alpha360_steady.py # NEW: steady book + Alpha360 feature_config
├── recipes/crossasset_steady.py # NEW: steady book + custom cross-asset handler
├── features/__init__.py       # NEW (package marker)
├── features/cross_asset.py    # NEW: cross_asset_features(panel,...) pure fn + CrossAssetProcessor + the handler class
├── scaffold.py                # MODIFY: handler_config(...) helper; build the handler from feature_config (replaces hardcoded Alpha158)
└── cpcv.py                    # MODIFY: _materialize_span builds the handler from feature_config via the same helper
tests/
├── test_experiment_recipe.py  # EXTEND: feature_config contract + benchmark-preservation + the two new recipes
├── test_cross_asset.py        # NEW: pure cross_asset_features tests (each family; leak-safety; BTC self-row)
├── test_experiment_scaffold.py# EXTEND (redis-gated): handler built from feature_config; Alpha158 preserved; the two new recipes run
└── test_experiment_cpcv.py    # EXTEND (redis-gated): _materialize_span builds from feature_config
```

## The seam

`Recipe.feature_config: dict` — `{"class": "Alpha158", "module_path": "qlib.contrib.data.handler"}`. The handler's runtime kwargs (`instruments`, `start_time`/`end_time`/`fit_*`, `infer_processors`, `learn_processors`, `label`) are assembled by the helper from `instruments`, `segments`, and the existing `handler_kwargs` — so `feature_config` carries only what varies (the class). `scaffold.handler_config(feature_config, instruments, segments, handler_kwargs)` returns the full `{class, module_path, kwargs}` dict; `scaffold.py` (dataset construction) and `cpcv.py:_materialize_span` both call it, replacing their hardcoded Alpha158 dict.

## Feature set (b): custom cross-asset handler

- **`cross_asset_features(panel: pd.DataFrame, *, btc="BTCUSDT", ...) -> pd.DataFrame`** — pure function: given a date×instrument panel of raw returns/close, returns the cross-asset feature columns (the families in Decision 6). Trailing windows only; cross-sectional rank is computed within each date across instruments (contemporaneous, no forward leak). BTC's own rows get neutral/self-referential values (beta 1, relative strength 0). Fully unit-testable on a synthetic panel.
- **`CrossAssetProcessor(Processor)`** — thin qlib wrapper: in `__call__(df)` it extracts the needed raw columns from the loaded panel, calls `cross_asset_features`, appends the new columns. Registered as an `infer_processor`/feature step in the custom handler.
- **The handler class** — subclasses Alpha158's data handler, adding the raw helper field(s) the processor needs and the `CrossAssetProcessor` to the feature pipeline (then dropping raw helpers from the model-visible columns). Referenced by `crossasset_steady`'s `feature_config`.

Leak-safety integrates with CPCV unchanged: all cross-asset features use trailing windows, so the existing purge (`label_horizon_days`) + embargo remain sufficient; no new leakage surface.

## Validation & verdict

At closeout, run the four recipes (`crossasset_steady`, `alpha360_steady`, `steady`, `skeleton`) full-CPCV into an isolated out-dir, then `zcrypto rank`. Record, honestly, whether either richer feature set clears a meaningful net OOS Sharpe / PSR bar versus the benchmarks, or whether the edge stays absent (CPCV→holdout inversion persists). The verdict lands in the new recipe docstrings (like `steady`/`regime_steady`) and the iterations-history entry. If no feature set clears the bar, that is the headline finding and the next fork is pivot-family (research §13).

## Benchmark preservation

`skeleton`, `steady`, `regime_steady` must build the **identical** Alpha158 handler config after the migration (only the construction path changes, not the result). A regression test asserts the built handler config equals the pre-iteration form. Walk-forward, the strategy seam, and the CPCV engine are untouched.

## Scope & deferred

- **In scope:** the feature seam, `Alpha360` + custom cross-asset handlers, the two demo recipes, the A/B validation, and the docs/closeout.
- **Out of scope (new open-topic at closeout):** funding-rate / on-chain / order-book features — they require a new data source beyond daily OHLCV klines.
- **Untouched:** strategy/walk-forward/CPCV logic; the data pipeline; the universe.

## Closeout tasks (authored when the work is real)

- Flip open-topic `T0008` to `partial` (seam + two handlers shipped) or `resolved`, per outcome.
- Open a new open-topic for non-OHLCV (funding/on-chain) features.
- README `## Usage`: document `feature_config`, the `alpha360_steady` + `crossasset_steady` recipes.
- The validation run + honest verdict (docstrings + iterations-history iter-13 entry).
