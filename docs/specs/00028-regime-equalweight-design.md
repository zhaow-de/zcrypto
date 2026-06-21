# Does the cross-sectional selection add OOS value? (regime-gated equal-weight) — Design

**Iteration:** iter-29
**Advances open-topic:** `T0018` (OOS wall) — isolates how much of `regime_voltarget`'s edge is selection vs market-timing.
**Builds on:** iter-24 (`regime_voltarget`, the best recipe), iter-27 (the `_fit_predict` seam — runs any sklearn model), iter-23 (`RegimeGatedTopkStrategy`).

## Context — what

The wall (T0018) shows the Alpha158 cross-sectional signal inverts OOS across features/model/target. But `regime_voltarget` (Alpha158 top-10 + the gate) still posts the best OOS mean (0.311) — almost entirely from the gate's bear-avoidance. Open question: **does the Alpha158 *selection* contribute anything OOS, or is the entire edge BTC-trend market-timing?** Test a **no-selection** book — hold the whole universe equal-weight, same gate — against `regime_voltarget`.

## Why this matters

If regime-gated equal-weight ≈ `regime_voltarget`, the entire Alpha158/LGBM pipeline adds nothing deployable OOS, and the strategy reduces to a dramatically simpler, more robust thing: **"BTC-trend-time an equal-weight crypto basket."** That is a major simplification and a clean statement of where the real (defensive) edge lives. If `regime_voltarget` beats equal-weight, the selection does add bull-window value worth keeping. Either way it sharply characterizes the one surviving edge — useful for the human's on-chain-vs-accept-ceiling decision at the gate.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **One new recipe `regime_equalweight`** = `steady`'s book with `model_config = {"class": "DummyRegressor", "module_path": "sklearn.dummy", "kwargs": {"strategy": "mean"}}` (a constant signal — no selection, via the iter-27 `_fit_predict` generic branch) and `strategy_config = RegimeGatedTopkStrategy` with **`topk=19`** (= the full universe → hold all, equal-weight) + the iter-24 gate (`regime_mode="binary"`, `regime_ma_window=200`, `vol_target=0.50`, `regime_benchmark="BTCUSDT"`, `n_drop=1`, `hold_thresh=5`). | `DummyRegressor(strategy="mean")` predicts a constant for every row → no cross-sectional ranking; `topk=19` (the universe size) makes `TopkDropoutStrategy` hold all names equal-weight. Same gate as `regime_voltarget`, so the ONLY difference vs `regime_voltarget` is selection (top-10 Alpha158) vs no-selection (all-19 equal-weight). Runs via the existing seam — no new infra. |
| 2 | **A/B on `zcrypto stress`** (`--seeds 8`): `regime_voltarget` (reused from disk) vs `regime_equalweight`. Read cost-adjusted Sharpe (`T0015`). | Direct selection-value test. Note: `DummyRegressor` is deterministic → the multi-seed distribution is a point (fine). |

## Component file tree

```
cli/experiment/recipes/
└── regime_equalweight.py  # NEW: steady's book + DummyRegressor model + RegimeGatedTopkStrategy(topk=19, binary 200d, vol_target=0.50).
tests/
└── test_experiment_recipe.py  # EXTEND: regime_equalweight resolves; model_config is DummyRegressor/sklearn.dummy/strategy=mean;
                               #         strategy is RegimeGatedTopkStrategy topk=19 + the gate kwargs; handler/feature/segments/
                               #         universe/fees match steady.
README.md                      # MODIFY: Usage — add regime_equalweight.
```

## A/B & verdict

Closeout (redis up): run `zcrypto stress --recipe regime_equalweight --seeds 8`; reuse `regime_voltarget` from disk. Per-window long-only Sharpe + mean / worst. Verdict → `docs/iterations-history.md`:
- `regime_equalweight` ≈ `regime_voltarget` → the Alpha158 selection adds nothing OOS; the edge is pure market-timing → strategy simplifies to gated equal-weight.
- `regime_voltarget` > `regime_equalweight` → selection adds (bull-window) value; quantify it.

## Scope & deferred

- **In:** the 1 recipe; the drift-guard test; the A/B + verdict; README; T0018 note.
- **Out:** on-chain data (T0010, the human-gated frontier); any new strategy code (equal-weight achieved via `topk=universe` + constant signal, no new strategy class).
- **Untouched:** the `_fit_predict` seam, `RegimeGatedTopkStrategy`, harnesses, data/cost layers.

## Closeout tasks (authored when the work is real)

- Run `regime_equalweight` stress; A/B vs `regime_voltarget` → record the selection-value verdict.
- iter-29 iterations-history entry; update `T0018` (how much of the edge is selection vs timing).
- README `## Usage`: `regime_equalweight`.
- At the 09:00 gate: hand back the on-chain (T0010) decision — the cheap OHLCV/regime vein is now exhausted.
