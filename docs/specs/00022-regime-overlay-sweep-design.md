# Regime-overlay responsiveness sweep — Design

**Iteration:** iter-23
**Relates to open-topic:** `T0003` (BTC-trend regime overlay) — stays **resolved/archived** (the overlay capability shipped in iter-12). This iteration is a *measured follow-up*: iter-12 only tried the slow binary-200d mode, single-run, on pre-survivorship / pre-realistic-cost data; here we measure gate **responsiveness** under current methodology. A *new* open-topic is opened only if a configuration shows promise (graded/vol-target/L-S-gating).
**Builds on:** iter-12 (`RegimeGatedTopkStrategy` + `regime_steady`), iter-14 (multi-seed holdout), iter-19 (realistic costs), iter-22 (`zcrypto stress` OOS harness).

## Context — what

The project's central unsolved problem: the long-only book loses to beta in the 2025-2026 bear holdout (`steady` cost-adjusted Sharpe −0.585), and the market-neutral L/S alpha did not survive OOS (iter-22). The canonical structural fix for bear-market beta drag is a **BTC-trend regime gate** — hold the long book in uptrends, flatten to cash in downtrends.

`regime_steady` (iter-12, `RegimeGatedTopkStrategy`, binary 200-day SMA gate) exists but its iter-12 verdict was a null: the **slow 200-day gate rarely engaged** ("BTC mostly above its 200-day MA"), so `regime_steady ≈ steady`. That measurement was **single-run, pre-multi-seed, pre-realistic-cost, pre-survivorship-free-data**, and only tried the slow binary mode. The diagnosed weakness — gate too sluggish to engage — is exactly what this iteration tests: does a **more responsive** gate (faster MA, SMA cross) defend the down-regimes where binary-200d failed?

## Why this matters

A well-timed regime gate is a genuine profitability path, not just a drawdown defense: it can let the long book **capture cross-sectional alpha in bull regimes** (long-only `steady` OOS Sharpe was **+1.24 on 2023**) while **sitting out bear regimes** (2022 / 2025). Across a full cycle that net can turn positive — a market-timed long book — where the raw long-only book is net-negative. iter-22's `zcrypto stress` gives us the across-window lens to see exactly this (does the gate lift the bear windows toward 0/positive without killing the bull window?). Either outcome is decisive: a validated regime defense (a usable building block), or a clean confirmation that no gate responsiveness rescues this signal/universe under current rigor.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Responsiveness sweep, 4 arms:** `steady` (no gate, baseline) · `regime_steady` (binary 200d, existing — re-measured) · **`regime_fast`** (binary 100d, NEW) · **`regime_cross`** (50/200-day SMA golden-cross, NEW). | Directly tests the iter-12-diagnosed weakness (gate too slow). The `RegimeGatedTopkStrategy` already supports `binary`(`regime_ma_window`) and `cross`(`regime_ma_fast`,`regime_ma_window`), so the new arms are pure recipe knob-tweaks — minimal build. |
| 2 | **New recipes copy `steady`'s book verbatim** (same Alpha158 / regularized LGBM / 5-day label / segments / universe / fees) and add ONLY the regime strategy; **no `wf_enabled`** (match `steady`). | Clean isolation: the single change vs `steady` is the regime gate, so the A/B attributes any delta to gating responsiveness alone. (The multi-seed holdout does a single fit and ignores `wf_enabled` anyway — see Decision 4 — so `regime_steady`'s inert `wf_enabled=True` does not break comparability.) |
| 3 | **Two measurement axes, both reusing existing harnesses:** (a) **multi-seed cost-realistic holdout** A/B (`run_holdout_seeds`, `--seeds 8 --deterministic`) — paired per-seed Δ(cost-adjusted Sharpe) vs `steady`; (b) **`zcrypto stress`** OOS walk-forward across 2022/2023/2024/2025 per arm. | (a) gives a precise paired delta on the dev holdout; (b) gives the OOS across-window picture that is the real test of a market-timing gate (and de-risks the dev-seen-holdout selection bias). Read the **cost-adjusted Sharpe**, never gross `ending_value` (`T0015`). |
| 4 | **The multi-seed holdout exercises the recipe's strategy** (`multiseed._light_holdout` → `strategy_config_with_signal(recipe.strategy_config, signal)`), so the regime gate IS applied; all arms share the same single-fit per-seed signal and differ only in the gate. | Confirmed by reading `cli/experiment/multiseed.py:194`. This is what makes the holdout A/B a valid isolation of the gate. |
| 5 | **Scope to 3 regime arms; defer `graded` mode + vol-targeting** to a follow-up note. | Keeps the iteration small (2 new recipe files). `binary-100d` and `50/200-cross` are the two cleanest "more responsive" hypotheses; graded/vol-target add parameters and are only worth trying if responsiveness shows signal. |

## Component file tree

```
cli/experiment/recipes/
├── regime_fast.py    # NEW: steady's book verbatim + RegimeGatedTopkStrategy binary, regime_ma_window=100.
└── regime_cross.py   # NEW: steady's book verbatim + RegimeGatedTopkStrategy cross, regime_ma_fast=50, regime_ma_window=200.
tests/
└── test_experiment_recipe.py  # EXTEND: regime_fast / regime_cross resolve; wire RegimeGatedTopkStrategy with the right
                               #         regime kwargs (fast: binary/ma_window=100; cross: cross/ma_fast=50/ma_window=200);
                               #         book (model/handler/label/segments/universe/fees) matches steady (drift guard,
                               #         mirroring the existing regime_steady/funding_steady recipe tests).
README.md                      # MODIFY: Usage — add regime_fast + regime_cross to the recipe list.
```

(Recipes are auto-discovered — `resolve_recipe` globs the recipes dir for modules exposing `RECIPE` — so no registry edit is needed.)

## Recipe definitions (the only deltas vs `steady`)

Both copy `steady`'s `handler_kwargs` / `model_config` / `feature_config` / `segments` / `universe` / `reference_instruments` / `account` / `benchmark` / `fee_preset` / `label_horizon_days` / `feature_lookback_days` / `cv_*` verbatim, and set `strategy_config`:

- **`regime_fast`** — `RegimeGatedTopkStrategy`, `kwargs={topk:10, n_drop:1, hold_thresh:5, regime_mode:"binary", regime_benchmark:"BTCUSDT", regime_ma_window:100, vol_target:None}`.
- **`regime_cross`** — same, but `regime_mode:"cross", regime_ma_fast:50, regime_ma_window:200`.

(Match `regime_steady`'s `topk/n_drop/hold_thresh` so the books are identical apart from the gate signal.)

## A/B & verdict

Closeout runs, with redis up:
- **Holdout A/B:** `run_holdout_seeds(--seeds 8 --deterministic)` for `steady`, `regime_steady`, `regime_fast`, `regime_cross`; record per-seed cost-adjusted Sharpe + the paired Δ(regime − steady).
- **OOS stress:** `zcrypto stress --recipe <r> --seeds 8` for each arm; record per-window long-only Sharpe (2022/2023/2024/2025) + the across-window mean / worst.

Verdict → `docs/iterations-history.md`:
- Does any regime arm meaningfully **improve risk-adjusted return vs `steady`** — especially lift the **bear windows (2022, 2025) toward 0/positive while preserving the bull window (2023 +1.24)** — i.e., a net-positive market-timed long book? Or does no responsiveness setting help (confirming iter-12 under current methodology)?
- Does a **faster** gate (100d / 50-200 cross) engage where the slow 200d did not?

## Scope & deferred

- **In:** the 2 new regime recipes; the recipe-resolution/drift tests; the holdout + OOS-stress A/Bs and verdict; README recipe list; iter-23 history entry (and a new follow-up topic iff a gate shows promise).
- **Out (deferred, noted as follow-ups):** `graded` mode + vol-targeting variants; applying the regime gate to a market-neutral/L/S book; any model/label/universe change (book held constant for a clean A/B).
- **Untouched:** `RegimeGatedTopkStrategy` itself (reused as-is), the multi-seed / stress harnesses, the data and cost layers.

## Closeout tasks (authored when the work is real)

- Run the holdout A/B + the OOS stress for the 4 arms → record the cost-adjusted-Sharpe verdict (does responsiveness rescue the bear regimes / produce a net-positive timed book?).
- iter-23 iterations-history entry (the 2 recipes + the responsiveness verdict); `T0003` stays resolved/archived (note the measured follow-up in the history entry, not by un-archiving).
- README `## Usage`: `regime_fast` + `regime_cross`.
- If a regime configuration helps, open a **new** `docs/open-topics/` topic for the follow-up (graded/vol-target tuning, or regime-gating a market-neutral book); if none helps, the history entry records the confirmed null under current methodology.
