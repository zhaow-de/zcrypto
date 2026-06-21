# Concentration sensitivity: top-5 mega-cap gated basket — Design

**Iteration:** iter-31
**Advances open-topic:** `T0018` — one more principled point on the (now EV-positive) basket-construction axis.
**Builds on:** iter-30 (`regime_equalweight_majors` = gated equal-weight on 10 majors, the best recipe at OOS mean Sharpe 0.493).

## Context — what

iter-30 showed basket quality matters: concentrating from 19 coins to the 10 large-cap majors improved both mean (0.382→0.493) and the worst window (the thin/newer alts dragged, especially in the 2025 bear). Open question: does *further* concentration into the **top-5 mega-caps** keep helping, or is 10-major the diversification sweet spot? This maps the concentration/diversification tradeoff with one more principled liquidity tier.

## Why this matters

A cheap, safe robustness check on the live universe axis — the one OHLCV-side lever still showing EV. **Discipline note:** this is *one principled extra point* (the 5 most-liquid mega-caps), NOT an OOS grid-search of universe size; 10-major stays the principled default unless top-5 is clearly and robustly better. The result characterises whether the basket-quality edge is monotonic with concentration (informative for deployment) without over-fitting the universe to the holdout.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **One new recipe `regime_equalweight_top5`** = `regime_equalweight_majors` verbatim EXCEPT `universe` = the 5 mega-caps (`BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT`) and `strategy_config["kwargs"]["topk"] = 5` (= the new universe size → still hold-all equal-weight). | Isolates concentration as the single change vs the 10-major best. `topk` must equal the universe size (5) to stay equal-weight. Same DummyRegressor (no selection) + same gate (binary 200d + vol_target 0.50) + `steady` data book. |
| 2 | **A/B on `zcrypto stress`** (`--seeds 8`): `regime_equalweight_majors` (10, reused) vs `regime_equalweight_top5` (5). Read cost-adjusted Sharpe (`T0015`). | Direct concentration A/B. |

## Component file tree

```
cli/experiment/recipes/
└── regime_equalweight_top5.py  # NEW: regime_equalweight_majors with the 5 mega-caps + topk=5.
tests/
└── test_experiment_recipe.py   # EXTEND: resolves; universe == the 5 mega-caps; topk == 5 == len(universe);
                                #         model_config + gate kwargs match regime_equalweight_majors; data book matches steady.
README.md                       # MODIFY: Usage — add regime_equalweight_top5.
```

## A/B & verdict

Closeout (redis up): run `zcrypto stress --recipe regime_equalweight_top5 --seeds 8`; reuse `regime_equalweight_majors`. Per-window long-only Sharpe + mean / worst. Verdict → `docs/iterations-history.md`: does top-5 beat top-10? Is the basket-quality edge monotonic with concentration, or does 10 diversify better? Keep 10-major as the principled default unless top-5 is clearly+robustly better.

## Scope & deferred

- **In:** the 1 recipe; the drift-guard test; the A/B + verdict; README; T0018 note.
- **Out:** vol-weighted baskets (custom strategy — deferred to an attended iteration); further universe-N points (overfitting); on-chain (T0010).
- **Untouched:** the strategy/seam/harness/data layers.

## Closeout tasks (authored when the work is real)

- Run `regime_equalweight_top5` stress; A/B vs `regime_equalweight_majors` → record the concentration verdict + the running best.
- iter-31 iterations-history entry; update `T0018`; README.
- At the 09:00 gate: comprehensive hand-back (best strategy, the wall, vol-weighting + on-chain as the human-decision next steps).
