# Curated large-cap basket vs broad basket (gated equal-weight) — Design

**Iteration:** iter-30
**Advances open-topic:** `T0018` — a universe-knob A/B against the current best (`regime_equalweight`).
**Builds on:** iter-29 (`regime_equalweight` = gated equal-weight, the project's best recipe at OOS mean Sharpe 0.382).

## Context — what

`regime_equalweight` (BTC-trend-gated, hold all 19 coins equal-weight) is the best/simplest strategy. But the 19-coin universe includes thin/newer coins — `ARBUSDT`/`APTUSDT`/`PEPEUSDT` launched 2022-23 and are absent in early OOS windows, and several alts are far less liquid than the majors. Does a **curated large-cap basket** (the 10 most-established majors, all with full 2020+ history) beat the broad basket?

## Why this matters

Pure knob-tweak A/B vs the current best (the skill's prescribed out-of-backlog move). It answers a real deployment question — *which* basket to regime-time — and tests whether basket quality/breadth matters: speculative thin alts may drag the broad basket, or breadth may diversify better. Either way it refines the one deployable strategy. (Honest expectation: modest effect; the cheap research vein is otherwise exhausted, with on-chain — T0010 — the human-gated frontier.)

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **One new recipe `regime_equalweight_majors`** = `regime_equalweight` verbatim EXCEPT `universe` = the 10 established majors (`BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, AVAXUSDT, LINKUSDT, DOGEUSDT, TRXUSDT`) and `strategy_config["kwargs"]["topk"] = 10` (= the new universe size → still hold-all equal-weight). | Isolates the universe as the single change vs `regime_equalweight`. `topk` must equal the new universe size to remain equal-weight (hold all). All 10 have full 2020+ history (consistent basket across all OOS windows). Same DummyRegressor + same gate. |
| 2 | **A/B on `zcrypto stress`** (`--seeds 8`): `regime_equalweight` (19-coin, reused) vs `regime_equalweight_majors` (10-coin). | Direct basket A/B; read cost-adjusted Sharpe (`T0015`). |

## Component file tree

```
cli/experiment/recipes/
└── regime_equalweight_majors.py  # NEW: regime_equalweight with the 10-major universe + topk=10.
tests/
└── test_experiment_recipe.py     # EXTEND: resolves; universe is the 10 majors; topk == 10 == len(universe);
                                  #         model_config = DummyRegressor; gate kwargs match regime_equalweight;
                                  #         data book (handler/feature/segments/fees) matches steady.
README.md                         # MODIFY: Usage — add regime_equalweight_majors.
```

## A/B & verdict

Closeout (redis up): run `zcrypto stress --recipe regime_equalweight_majors --seeds 8`; reuse `regime_equalweight` from disk. Per-window long-only Sharpe + mean / worst. Verdict → `docs/iterations-history.md`: does the large-cap basket beat the broad basket? If meaningfully better → a cleaner deployable basket; if not → breadth is fine, basket choice is second-order.

## Scope & deferred

- **In:** the 1 recipe; the drift-guard test; the A/B + verdict; README; T0018 note.
- **Out:** vol-weighted/risk-parity baskets (need a custom weighting strategy); on-chain (T0010).
- **Untouched:** the strategy/seam/harness/data layers.

## Closeout tasks (authored when the work is real)

- Run `regime_equalweight_majors` stress; A/B vs `regime_equalweight` → record the basket verdict + the (running) best recipe.
- iter-30 iterations-history entry; update `T0018`.
- README `## Usage`: `regime_equalweight_majors`.
- At the 09:00 gate: comprehensive hand-back (best strategy, the wall, the on-chain decision).
