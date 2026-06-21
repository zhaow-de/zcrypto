# 00011 — Scaffold extension: pluggable strategy, BTC-regime overlay, walk-forward retraining

- **Date:** 2026-06-19
- **Status:** Approved design (pre-plan)
- **Iteration:** iter-12
- **Scope:** Open the experiment scaffold's hardcoded **strategy** seam so strategies
  are recipe-pluggable; ship (A) a parameterized **BTC-trend regime overlay**
  (resolves open-topic `T0003`) and (B) **walk-forward retraining** for the holdout.
  Both are direct responses to the regime non-stationarity the `steady` validation
  exposed. All from existing daily-kline data — **no new data**.
- **Depends on:** spec `00006` (experiment scaffold), `00008` (CPCV), `00010`
  (PSR/DSR/PBO + `rank`).
- **Resolves:** open-topic `T0003` (BTC-trend regime overlay + vol-targeting).

## Goal

Turn the scaffold from "one hardcoded long-only, always-invested strategy trained
once" into "a recipe picks its strategy, and the strategy can gate exposure off a
BTC-trend regime; the holdout can retrain walk-forward." This attacks the failure
mode the `steady` recipe surfaced (PR #41): a model with a *positive* CPCV
out-of-sample Sharpe on 2020–2024 (~+1.0) that **inverts to negative** on the
untouched 2025–2026 holdout (~−0.63), PBO 0.91 — a market-regime shift. The two
levers here are the two scaffold-level answers to that: **gate the left tail**
(regime overlay) and **let the model adapt** (walk-forward).

## Background & constraints

- **Regime change is the live risk.** Research §5 ranks risks: fees, overfitting,
  slippage, survivorship, **regime change** — and regime change is exactly what the
  `steady` exercise empirically hit. Research §13 Stage 3 names "add the BTC-trend
  regime filter and volatility-targeting overlay" as the current stage's work.
- **Spot-only ⇒ long/cash.** No shorting; the overlay scales *gross exposure* down
  toward cash (USDC), it does not go short.
- **No new data.** The regime signal is computed from the existing BTCUSDT klines;
  walk-forward re-slices the existing history.
- **HARD CONSTRAINT — preserve the benchmarks.** `skeleton` and `steady` must behave
  **identically** after this change so they remain valid benchmarks. The seam
  migration is behavior-preserving: they keep `TopkDropoutStrategy` with the same
  kwargs and walk-forward off; the single-fit holdout path and the CPCV path are
  unchanged for them. A regression test asserts the built strategy class + kwargs
  are unchanged.
- **Overfitting caveat.** Every new knob widens the config search space; DSR/PBO
  (from `00010`) will deflate accordingly. Defaults are deliberately minimal
  (binary-200d regime, vol-targeting off) to keep the baseline robust.

## Decisions (resolved during brainstorming)

| Fork | Decision |
| --- | --- |
| Scope | **A + B in one spec, two-phase plan** (Phase A: seam + regime; Phase B: walk-forward). Each phase independently shippable. |
| Strategy seam | Recipe gains **`strategy_config`** (full `init_instance_by_config` dict, mirrors `model_config`), **replacing** `strategy_kwargs`. The `signal=(model, dataset)` is injected at runtime. Touches both `scaffold.py` (holdout) and `cpcv.py` (path backtests). |
| Regime modes | **All three** (`binary` / `graded` / `cross`) are **recipe tuning points** on one parameterized strategy; default **`binary` @ 200-day SMA**. (A faster *single*-MA filter is just `binary` with a smaller `regime_ma_window`; `cross` is the dual-MA case.) |
| Vol-targeting | A **knob on the regime strategy, default OFF**. |
| Walk-forward | Holdout-only; **quarterly + expanding** default; cadence (`wf_retrain_freq`) and window (`wf_window` ∈ expanding/rolling, `wf_rolling_years`) are recipe knobs. **Orthogonal to CPCV**; composable with `--quick`. |
| Benchmark preservation | `skeleton` + `steady` migrate behavior-preservingly (`wf_enabled=False`, identical `TopkDropout`); regression test guards it. |
| Deferred | Enhance `T0004` (parametric size-scaled slippage, separable from data-gated aggTrades maker-fill); new `T0007` (multi-window stress harness); new `T0008` (pluggable feature handler). Authored at closeout. |

## Components

```
cli/experiment/
├── recipes/base.py        # MODIFY: strategy_config replaces strategy_kwargs; add wf_* knobs
├── recipes/skeleton.py    # MODIFY: migrate to strategy_config (behavior-preserving)
├── recipes/steady.py      # MODIFY: migrate to strategy_config (behavior-preserving)
├── recipes/regime_steady.py  # NEW: demo recipe = steady's book + regime overlay + walk-forward
├── strategies/__init__.py # NEW (package)
├── strategies/regime.py   # NEW: RegimeGatedTopkStrategy(TopkDropoutStrategy)
├── walkforward.py         # NEW: pure period-splitting (build_wf_periods)
├── scaffold.py            # MODIFY: build strategy from strategy_config; walk-forward holdout loop
└── cpcv.py                # MODIFY: build strategy from strategy_config (path backtests)
docs/open-topics/          # CLOSEOUT: T0003 resolved; T0004 enhanced; T0007 + T0008 new
README.md                  # CLOSEOUT: Usage (regime recipe, strategy_config, wf knobs)
docs/iterations-history.md # CLOSEOUT: iter-12 entry
```

## Phase A — pluggable strategy seam + regime overlay

### A1. The seam (`base.py`, `scaffold.py`, `cpcv.py`)

- **`Recipe.strategy_config: dict`** — a full `{class, module_path, kwargs}` dict,
  replacing `strategy_kwargs`. A shared helper `build_strategy(strategy_config,
  model, dataset)` (in `scaffold.py`) returns
  `init_instance_by_config({**strategy_config, "kwargs": {**strategy_config["kwargs"],
  "signal": (model, dataset)}})` — injecting the runtime signal. Both
  `scaffold._port_analysis_config` and `cpcv.py`'s per-path backtest call it
  (cpcv injects `signal=path_signal` instead of `(model, dataset)` — the helper
  takes the signal argument).
- **Migration:** `skeleton`/`steady` set
  `strategy_config={"class": "TopkDropoutStrategy", "module_path":
  "qlib.contrib.strategy.signal_strategy", "kwargs": {<their current topk/n_drop[/hold_thresh]>}}`.
  Identical built strategy ⇒ identical behavior.

### A2. The regime strategy (`strategies/regime.py`)

`RegimeGatedTopkStrategy(TopkDropoutStrategy)` — the cross-sectional ranker still
picks top-k; the overlay scales *gross exposure* via qlib's native
`get_risk_degree(trade_step)` market-timing hook (the rest stays cash).

- **`__init__`** stores the regime kwargs and **precomputes** a per-date exposure
  multiplier: query `D.features([regime_benchmark], ["$close"])` over the available
  span, compute the rolling SMA(s) (+ realized vol if vol-targeting), map each date
  to a multiplier per `regime_mode`. Store as a date→multiplier Series.
- **`get_risk_degree(trade_step)`** returns `base_risk_degree * multiplier[date]`
  (× the vol-target scale if enabled).
- **Modes:**
  - `binary`: close > SMA(`regime_ma_window`) → 1.0, else 0.0. (A "faster" filter
    is this mode with a smaller `regime_ma_window`, e.g. 100.)
  - `graded`: close > SMA·(1+`regime_band`) → 1.0; within ±band → `chop_exposure`
    (e.g. 0.5); below SMA·(1−band) → 0.0.
  - `cross`: dual-SMA cross — SMA(`regime_ma_fast`) > SMA(`regime_ma_window`) → 1.0,
    else 0.0 (e.g. 50/200).
- **Vol-targeting (knob, default off):** if `vol_target` set, multiply by
  `min(1, vol_target / realized_vol(vol_lookback))`.
- **Recipe-tunable kwargs:** `regime_mode`, `regime_benchmark="BTCUSDT"`,
  `regime_ma_window=200`, `regime_ma_fast=None`, `regime_band=0.0`,
  `chop_exposure=0.5`, `vol_target=None`, `vol_lookback=30` (+ the inherited
  `topk`/`n_drop`/`hold_thresh`).
- **Edge cases (tested):** dates before a full MA window → multiplier 1.0 (can't
  gate without the signal — fail toward invested, documented); a benchmark date
  missing → carry forward the last multiplier; vol with insufficient lookback → no
  vol scaling.

### A3. Demo recipe (`recipes/regime_steady.py`)

`regime_steady` = `steady`'s book + model (so the comparison isolates the
overlay's effect on steady's known holdout failure) with `strategy_config`
pointing at `RegimeGatedTopkStrategy` (`binary`, 200-day, vol-targeting off) and
walk-forward on (Phase B). Same universe/segments/fees ⇒ clean A/B vs
`skeleton`/`steady`. Tuned variants (varying the regime knobs) get their own
`regime_*` recipe files.

## Phase B — walk-forward retraining

- **`walkforward.py`** — pure `build_wf_periods(test_start, test_end, train_start,
  freq, window, rolling_years) -> list[tuple[(train_start, train_end),
  (predict_start, predict_end)]]`. Splits the **test** window into `freq` periods;
  per period the train range is `train_start..period_start` (expanding) or
  `(period_start − rolling_years)..period_start` (rolling).
- **`scaffold.py`** — when `recipe.wf_enabled`, the holdout is produced by looping
  the periods: fit the model on the train range, predict the period, backtest it
  with the recipe's strategy, and **stitch** the per-period daily returns into one
  holdout curve → the same `metrics` / holdout PSR / `returns.csv`. When
  `wf_enabled=False`, the existing single-fit holdout path runs unchanged.
- **Orthogonal to CPCV:** CPCV (validation over train+valid) is untouched.
  Walk-forward only changes how the **holdout** is produced. `--quick` still skips
  CPCV and produces the holdout (single-fit or walk-forward per the recipe).
- **`Recipe` knobs:** `wf_enabled=False`, `wf_retrain_freq="quarter"`,
  `wf_window="expanding"`, `wf_rolling_years=3`.

## Testing strategy

- **Pure unit (no qlib):**
  - `tests/test_regime_strategy.py` (or a pure helper split out) — the exposure
    multiplier on a synthetic BTC series: binary/graded/fast modes, vol-targeting
    on/off, warmup → 1.0, missing-date carry-forward.
  - `tests/test_walkforward.py` — `build_wf_periods` returns the expected
    (train, predict) tuples for quarterly/annual × expanding/rolling; covers the
    final partial period and the rolling-window start.
  - `tests/test_experiment_recipe.py` (extend) — **benchmark preservation**:
    `skeleton`/`steady` `strategy_config` builds a `TopkDropoutStrategy` with their
    original kwargs; `wf_enabled` defaults False; the `regime_steady` recipe
    resolves with the regime strategy + wf on.
- **redis-gated integration (extend):** a `regime_steady` run completes; with
  `wf_enabled` the holdout is stitched from >1 fit; the regime strategy's exposure
  is < 1.0 on dates in a known BTC downtrend within the span.

## Out of scope

- aggTrades-calibrated slippage / maker-fill (`T0004` data part); multi-window
  training stress (`T0007`); pluggable feature handler / Alpha360 (`T0008`);
  point-in-time universe (`T0005`); paper trading (`T0006`); long/short (spot — N/A).

## Closeout (executed at end of iteration)

- **`docs/open-topics/T0003`** → `status: resolved` (regime overlay + vol-targeting
  knob shipped); move its bullet to `## Resolved`.
- **`docs/open-topics/T0004`** → enhance `## Findings so far`: a parametric
  size-scaled slippage term is a scaffold extension separable from the data-gated
  aggTrades maker-fill; §13 Stage 2 specified it for the baseline.
- **`docs/open-topics/T0007`** (new) — multi-window training-stress harness
  (§13 Stage 3: stress across 2017 vs 2020 start + LUNA/FTX).
- **`docs/open-topics/T0008`** (new) — pluggable feature handler (Alpha360 / custom
  crypto features: momentum, funding, cointegration-deviations per §5).
- **README `## Usage`** — the `regime_steady` recipe, the `strategy_config` recipe field,
  and the `wf_*` knobs.
- **Validation run + verdict** — `regime_steady` vs `skeleton`/`steady` via CPCV + `rank`;
  record the honest result (does the overlay + walk-forward cut the left tail /
  improve risk-adjusted on the 2025–2026 holdout?).
- **`docs/iterations-history.md`** — the iter-12 entry.

## References

- `steady` negative verdict + the regime-mismatch evidence: PR #41,
  `docs/open-topics/T0003-btc-regime-overlay.md`.
- Research roadmap §5 (strategy family + regime overlay), §13 Stage 3 (robustness).
- qlib `TopkDropoutStrategy` / `BaseSignalStrategy.get_risk_degree`
  (`qlib/contrib/strategy/signal_strategy.py`).
