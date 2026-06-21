# Regime overlay refinement — graded + vol-target — Design

**Iteration:** iter-24
**Advances open-topic:** `T0017` (regime-overlay tuning) — the first two refinement levers it lists.
**Builds on:** iter-23 (the regime gate now actually engages after the qlib `get_risk_degree` workaround; the slow binary-200d gate `regime_steady` is the OOS winner — mean Sharpe 0.289 vs `steady` 0.154, worst −0.220 vs −0.753); iter-22 (`zcrypto stress` OOS harness); the iter-23 metric-sanitize fix (all-cash windows no longer crash).

## Context — what

iter-23 established that a BTC-trend regime gate, once wired, improves OOS risk-adjusted return — but only the **slow binary-200d** gate (`regime_steady`); faster gates whipsawed. The binary gate has two known weaknesses, visible in the iter-23 data: it is **all-or-nothing** (it gave up bull-window upside — 2023 1.244→0.877, 2024 0.700→0.498), and it is **volatility-blind** (full exposure whenever BTC is above its SMA, regardless of how violent the regime is). This iteration tests the two refinement levers `RegimeGatedTopkStrategy` already supports against those weaknesses.

## Why this matters

The regime-gated long book is the project's one OOS-robust result, but it is modest (mean 0.289) and defensive. If a **graded** gate recovers some of the surrendered bull upside (partial exposure in the chop zone instead of binary cash), or **vol-targeting** trims exposure in violent regimes to improve the worst-case, the defensive Sharpe could climb meaningfully — turning a capital-preservation overlay into something closer to a genuine timed-long strategy. A null (binary-200d is the sweet spot) is also a clean, useful finding that closes two T0017 levers.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **4 arms:** `steady` (no gate) · `regime_steady` (binary 200d — the iter-23 winner, baseline) · **`regime_graded`** (graded, 200d, NEW) · **`regime_voltarget`** (binary 200d + vol-targeting, NEW). | Isolates each refinement lever against the binary-200d winner. Both new arms are pure knob-tweaks on the existing strategy. |
| 2 | **`regime_graded` params:** `regime_mode="graded"`, `regime_ma_window=200`, `regime_band=0.05`, `chop_exposure=0.5`. | `graded` gives 1.0 above `sma·(1+band)`, 0.0 below `sma·(1−band)`, `chop_exposure` in between. A non-zero band (±5%) is REQUIRED for graded to differ from binary; 0.5 half-exposure in the chop zone is the natural midpoint. Targets the bull give-up (stays partially invested near the SMA). |
| 3 | **`regime_voltarget` params:** `regime_mode="binary"`, `regime_ma_window=200`, `vol_target=0.50` (annualized), `vol_lookback=30` (default). | Layers vol-targeting on the winning binary gate: `mult *= clip(vol_target/realized, ≤1)`, scaling exposure down when BTC's 30-day annualized realized vol exceeds ~50% (near BTC's typical vol). 0.50 is a reasonable first-pass target (itself tunable later). Targets vol-blindness / worst-case. |
| 4 | **Both new recipes copy `steady`'s book verbatim** (only `strategy_config` differs), `topk/n_drop/hold_thresh=10/1/5`, no `wf_enabled` — identical to the iter-23 regime recipes. | Clean isolation: the single change vs `regime_steady` is the gate mode/vol-target, so the A/B attributes any delta to the refinement. |
| 5 | **Measurement = the iter-22 `zcrypto stress` OOS harness** (`--seeds 8`), per-window long-only Sharpe across 2022/2023/2024/2025 for all 4 arms; read cost-adjusted Sharpe (`T0015`). | Same harness/methodology as iter-23, so the numbers are directly comparable to the iter-23 verdict table. The gate is now wired (iter-23) and all-cash windows no longer crash (iter-23 metric fix), so the run is valid. |

## Component file tree

```
cli/experiment/recipes/
├── regime_graded.py     # NEW: steady's book + RegimeGatedTopkStrategy graded/200d/band=0.05/chop=0.5.
└── regime_voltarget.py  # NEW: steady's book + RegimeGatedTopkStrategy binary/200d/vol_target=0.50.
tests/
└── test_experiment_recipe.py  # EXTEND: regime_graded / regime_voltarget resolve; wire the right regime kwargs;
                               #         book matches steady (drift guard, mirroring the iter-23 regime recipe tests).
README.md                      # MODIFY: Usage — add regime_graded + regime_voltarget to the recipe list.
```

(Recipes are auto-discovered — no registry edit.)

## A/B & verdict

Closeout (redis up): `zcrypto stress --recipe <r> --seeds 8` for `steady`, `regime_steady`, `regime_graded`, `regime_voltarget`; record per-window long-only Sharpe + across-window mean / worst, compared to the iter-23 table. Verdict → `docs/iterations-history.md`:
- Does **graded** recover bull-window upside (2023/2024) and/or lift the mean above `regime_steady`'s 0.289?
- Does **vol-targeting** improve the worst window / mean vs the plain binary gate?
- Or is binary-200d the sweet spot (closing these two T0017 levers)?

## Scope & deferred

- **In:** the 2 new recipes; the drift-guard tests; the 4-arm OOS-stress A/B + verdict; README; T0017 progress note in the history entry.
- **Out (deferred, stays in T0017):** anti-whipsaw confirmation filter; combining the gate with a market-neutral / L/S book; tuning the band/chop/vol_target values beyond this first pass; submitting the qlib bug upstream.
- **Untouched:** `RegimeGatedTopkStrategy` (reused as-is — graded + vol_target already implemented), the harnesses, data/cost layers.

## Closeout tasks (authored when the work is real)

- Run the 4-arm OOS stress → record the refinement verdict vs the iter-23 winner.
- iter-24 iterations-history entry (the 2 recipes + the graded/vol-target verdict); update `T0017`'s `## Findings so far` / `## Suggested next steps` with what these two levers showed (and trim them from the open list if conclusively settled).
- README `## Usage`: `regime_graded` + `regime_voltarget`.
- If a refinement clearly wins, note the new best recipe; if not, record binary-200d as the sweet spot.
