# Funding-edge monetization via market-neutral long/short — Design

**Iteration:** iter-21
**Builds on:** iter-20 (the funding feature + `funding_steady` signal), iter-19 (realistic costs), iter-14 (the multi-seed holdout).
**Open-topic:** none new — this is the "monetize the funding edge" follow-up the iter-20 verdict pointed to (a modest cross-sectional edge masked by long-only beta drag).

## Context — what

iter-20 found funding carries a modest, real **cross-sectional** edge over OHLCV (`funding_steady` vs `steady`, paired ΔSharpe +0.20, z≈2.0) — but every recipe still **loses absolutely** (Sharpe −0.42 to −0.59). The cause is **market-beta drag**: the 2025+ holdout is a bear market (BTC −32%, ETH −50%, SOL −65%), and the strategies are **long-only** (`TopkDropoutStrategy`; the iter-12 `RegimeGatedTopkStrategy` only gates long↔cash). A long-only book cannot escape that beta, so the cross-sectional alpha is masked.

The principled way to monetize a cross-sectional signal that's net-losing long-only in a down market is to **remove the market beta** — a **market-neutral long/short** book (long the predicted winners, short the predicted losers). This iteration measures whether the funding edge becomes positive absolute return once beta is removed.

## Why this matters

This is the difference between "funding has predictive value" (iter-20) and "funding makes money." A cross-sectional signal's monetizable form is the long-short quantile spread; if neutralizing the beta turns the −42% long-only book into a positive (or materially better) market-neutral return, the edge is real P&L. If it doesn't, that too is a real finding (the edge is too small / too costly to monetize daily). Either way it directly tests the project's central goal on the one signal that beat the baseline.

## Key technical fact (verified)

**qlib's `SimulatorExecutor` cannot short.** The Exchange SELL branch clips `order.deal_amount` to `min(current_amount, order.deal_amount)` with an explicit `# TODO: make the trading shortable` (`exchange.py:900`). A true long/short cannot be expressed in qlib's backtest. So the L/S is evaluated as a **quantile-spread** computed directly from the model's prediction signal + the price panel — the standard academic factor-monetization method — bypassing qlib's executor and reusing the already-trained signals.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **A long/short *spread evaluator*, not a qlib strategy.** A pure `long_short_spread(scores, fwd_returns, *, k=5, cost_per_side) -> dict` in a new `cli/experiment/longshort.py`: per date, rank instruments by predicted score → long the top-k (equal weight 1/k), short the bottom-k (equal weight), dollar-neutral; daily return = `mean(top-k fwd) − mean(bottom-k fwd) − cost`. Returns the daily spread Series + summary (Sharpe, cumulative/ending). | qlib can't short (above), and the quantile spread is the standard way to evaluate a cross-sectional factor's market-neutral return. Pure + qlib-free → unit-testable. Reuses the trained signal — no retraining. |
| 2 | **Construction: k=5 per leg, daily rebalance, 1-day-forward spread, equal-weight, dollar-neutral.** | Top-5 long / bottom-5 short of the 19-universe leaves a neutral middle; daily 1-day-forward is the cleanest, most-comparable factor spread. |
| 3 | **Costs: the iter-19 realistic per-side cost on daily turnover.** `cost_per_side` = `FEE_PRESETS[recipe.fee_preset][0] + (0 if recipe.fees_only else recipe.maker_fill_haircut)`; daily cost = `cost_per_side · (long-leg turnover + short-leg turnover)`, leg turnover = (names changed)/k. | A daily-rebalanced L/S can have high turnover, and the iter-19 finding was that the maker-fill haircut × turnover dominates — so the eval must charge it honestly, consistent with the long-only book's cost model. |
| 4 | **Integration into the multi-seed holdout.** `_light_holdout` returns `(report_df, signal)`; `_holdout_context` loads a 1-day-forward `$close`-return panel once (materialized across seeds, like the features); `_holdout_metrics_for_seed` computes the spread from `signal` + `ctx.fwd_ret` and adds **`ls_sharpe`** + **`ls_ending`** to the per-seed dict (alongside the existing long-only `sharpe`/`ending_value`). `summarize_seed_metrics` aggregates them automatically (it is generic over the dict keys). | Reuses the `--seeds N` machinery → every run reports both long-only and market-neutral metrics, and the A/B falls out for free. The forward-return panel loads once (no per-seed refetch). |
| 5 | **A/B + verdict (multi-seed, paired per-seed `ls_sharpe`):** `funding_steady` L/S vs `steady` L/S (does funding add edge market-neutral?) and `ls_sharpe` vs the long-only `sharpe` (does neutralizing the beta monetize?). | The paired per-seed difference isolates each effect; "monetized" iff the L/S spread Sharpe is materially positive AND funding lifts it beyond the seed-noise band. |

## Component file tree

```
cli/experiment/
├── longshort.py   # NEW: long_short_spread(scores, fwd_returns, *, k=5, cost_per_side=0.0) -> dict
│                  #      {"daily": Series, "sharpe": float, "ending": float} (account-normalized cumulative).
├── multiseed.py   # MODIFY: _light_holdout returns (report_df, signal); _holdout_context loads ctx.fwd_ret
│                  #         (1-day-fwd $close returns over the predict window, once); _holdout_metrics_for_seed
│                  #         adds ls_sharpe + ls_ending via long_short_spread. Long-only path byte-identical otherwise.
tests/
├── test_longshort.py          # NEW: long_short_spread on synthetic scores+returns with known answers — dollar-neutral
│                              #      spread sign/magnitude; equal-weight legs; turnover-cost subtraction; k clamping;
│                              #      a perfectly-predictive signal yields a positive spread; an inverted one negative.
├── test_experiment_multiseed.py # NEW or EXTEND: _holdout_metrics_for_seed adds ls_sharpe/ls_ending (monkeypatched
│                              #      _light_holdout returning a synthetic (report_df, signal) + a synthetic ctx.fwd_ret);
│                              #      long-only keys unchanged.
```

(No README change — the L/S metrics surface in `holdout_seeds.json`/logs, not a new CLI flag. The recipes are unchanged — the L/S is an evaluation over the existing signal.)

## `long_short_spread` definition (pure, leak-safe)

- Input: `scores` — Series `(datetime, instrument) -> predicted score`; `fwd_returns` — Series `(datetime, instrument) -> 1-day-forward return` (`close[t+1]/close[t] − 1`, aligned to date `t`).
- Per date `t`: drop instruments with NaN score or NaN fwd return; if fewer than `2k` remain, use `k' = floor(n/2)` (clamp); long = top-`k'` by score, short = bottom-`k'`; `spread_t = mean(fwd_returns over longs) − mean(fwd_returns over shorts)`.
- Turnover cost: leg turnover = |Δ(equal-weight membership)| one-way = (#names entering the leg)/k'; `cost_t = cost_per_side · (turnover_long + turnover_short)`; `net_t = spread_t − cost_t`.
- Output: daily `net` Series; `sharpe` = annualized `mean/std·√252`-style via the same `risk_analysis` information-ratio definition the long-only metric uses (for comparability); `ending` = `account · ∏(1 + net)` (account=1.0 normalized → a growth multiple). Leak-safe: uses only the same-day cross-section + the realized 1-day-forward return (the standard factor convention; no use of future scores).

## A/B & verdict

Run `funding_steady` and `steady` at `--seeds 16 --deterministic` (realistic-cost default). Per seed the holdout now emits `ls_sharpe` + `ls_ending` next to the long-only `sharpe`/`ending_value`. Compute the **paired per-seed** `ls_sharpe` difference `funding_steady − steady` (funding's market-neutral contribution) and compare the `ls_sharpe` distribution to the long-only `sharpe` distribution (the beta-removal effect). Verdict → `docs/iterations-history.md`: is the funding edge monetizable market-neutral, net of realistic daily-turnover costs?

## Scope & deferred

- **In:** the `long_short_spread` evaluator; the multi-seed holdout integration (signal exposure, fwd-return panel, `ls_sharpe`/`ls_ending`); the A/B + verdict.
- **Out:** a qlib short-capable executor/strategy (blocked by qlib — a large upstream change); crediting *actual perp-funding carry* to P&L (a separate lever — this iteration monetizes the *predictive* edge by removing beta, not the literal carry yield); any new signal/label (reuses `funding_steady`).
- **Untouched:** the recipes (the L/S is an evaluation over their existing signal); the long-only backtest path (still computed for the baseline); the data/cost layers.

## Closeout tasks (authored when the work is real)

- Run `funding_steady` + `steady` at `--seeds 16` → record the paired `ls_sharpe` verdict (funding's market-neutral contribution) and the L/S-vs-long-only comparison (does neutralizing monetize?), net of realistic costs.
- iter-21 iterations-history entry (the L/S spread evaluator + the monetization verdict, incl. the turnover-cost reality).
