# Realistic execution costs — Design

**Iteration:** iter-19
**Resolves open-topic:** `T0004` (realistic execution: size-scaled slippage + maker-fill) → **`resolved`** at closeout — the calibration + cost-model wiring + re-measure on top of iter-17's aggTrades sample.
**Depends on:** iter-17 (the aggTrades sample in the mirror), iter-14 (the multi-seed holdout A/B), iter-18 (the re-measure pattern).

## Context — what

The experiment cost model is **fees-only**: `exchange_kwargs(recipe)` sets `open_cost`/`close_cost` from `FEE_PRESETS` (12 bps round-trip, VIP2+BNB) with frictionless fills at the close — no slippage, 100% maker fills. `T0004` wants size-scaled slippage + maker-fill realism, which must be **calibrated** from trade-level data the daily dataset lacks. iter-17 acquired a bounded, liquidity-spanning aggTrades sample (`BTCUSDT`/`ETHUSDT`/`SOLUSDT`/`LINKUSDT`/`ATOMUSDT`/`PEPEUSDT` × 2024-12-01..2025-02-28, ~6 GB in the mirror; columns `agg_trade_id, price, quantity, first_id, last_id, timestamp_µs, is_buyer_maker, is_best_match`).

This iteration **calibrates** realistic costs from that sample, makes them the **default** cost model, and **re-measures** all recipes vs fees-only to quantify the net-P&L haircut.

## Why this matters

Research §6/§8/§13 — slippage and unfilled maker orders are where frictionless backtests diverge from live P&L; thin books (Tier-3, PEPE) slip materially, and the low/zero-fee economics depend on maker limit orders actually filling. Ignoring this overstates net returns, especially as turnover rises. Making calibrated costs the default means every future run is honest by default; fees-only becomes an explicit comparison baseline.

## Key qlib facts (verified)

- `Exchange.impact_cost` applies an **additive cost ratio** `impact_cost × (order$ / bar$-volume)²`, computed **per instrument** (`total_trade_val = get_volume(instrument) × deal_price` — the instrument's own bar), added to `open_cost` (BUY) / `close_cost` (SELL). So a single coefficient **self-adjusts by liquidity** (a thin pair's smaller bar-volume → larger ratio → more slippage); `exchange.py:877,890-895,920`.
- qlib has **no fill-probability hook** — orders are assumed to fill at the deal price. Maker-fill realism is therefore modeled as an **effective-cost haircut** (a bump to the fee fractions), not a custom executor.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Calibration = a one-off script** (`cli/experiment/scripts/calibrate_execution.py`, mirroring `backfill_funding.py`/`acquire_old_luna.py`) that parses the aggTrades mirror sample and emits committed constants. Output: a `COST_CALIBRATION` constants block in `cli/experiment/` that the recipe/`exchange_kwargs` consume. | The sample is fixed and the calibration is a one-time estimation; committed constants match how `FEE_PRESETS` already live as constants. A reusable CLI command would be over-engineering (YAGNI). |
| 2 | **Slippage = qlib's `impact_cost`, coefficient `c` calibrated from the sample.** Fit `c` to the `c·(order$/bar$-vol)²` form from the realized price-impact-vs-size in the trades, **per liquidity tier** (deep/mid/thin by daily $-volume), then **let the data decide** single global `c` vs a small per-tier mapping. | The `(v/V)²` form already self-adjusts for liquidity; the only open question is whether the coefficient's magnitude differs by tier. No custom slippage code — just a calibrated scalar (or a tiny tier→`c` map). Subsumes the iter-12 "12 bps + size×volume" parametric term (now data-estimated, not guessed). |
| 3 | **Maker-fill = an effective-cost haircut.** Per tier, estimate the maker-fill rate `f` and effective spread `s` from the trade flow + `is_buyer_maker`; the non-filled fraction pays taker, so the effective fee becomes `open/close_cost ≈ maker_fee + (1−f)·(s/2 + taker_premium)`. Folded into the `open_cost`/`close_cost` fractions. | qlib has no fill hook; the haircut keeps the model inside `exchange_kwargs` (no custom executor). At daily granularity it approximates fill realism for day-close orders of the strategy's typical size — defensible and documented as an approximation. |
| 4 | **Calibrated costs are the DEFAULT.** The `Recipe` gains cost params (the impact coefficient + the maker-fill haircut), defaulting to the calibrated values; `exchange_kwargs` assembles `impact_cost` + the haircut-adjusted fees. A **`--fees-only` opt-out flag** (default off) on `zcrypto experiment` reverts to the raw `fee_preset` + `impact_cost=0` (today's behavior) — the comparison baseline. | The principled end state: every run is honest by default. `--fees-only` provides the A/B baseline and a reproducible "old number." (This intentionally changes every recipe's headline result — not byte-identical — the point of the iteration.) |
| 5 | **Re-measure all recipes calibrated-default vs `--fees-only`** via the iter-14 multi-seed holdout (`--seeds 16 --deterministic`) → the per-recipe net-P&L haircut. | The cost change affects every recipe; quantifying the haircut against the seed-noise band is the verdict. Caveat (carried from iter-18): the multi-seed holdout runs the base strategy, so `regime_steady` ≡ `steady`. |

## Component file tree

```
cli/experiment/
├── costs.py            # NEW: COST_CALIBRATION constants (calibrated impact coef + maker-fill haircut, per tier or global) + a tier-resolver helper + realistic_exchange_kwargs assembly inputs.
├── scripts/
│   ├── calibrate_execution.py  # NEW: one-off — parse the aggTrades mirror sample → estimate (c, f, s) per tier → print + write the COST_CALIBRATION constants. Idempotent (re-run reproduces the same constants).
│   └── README.md               # NEW (cli/experiment/scripts/): register calibrate_execution.py (purpose, usage, NOT a routine flow).
├── recipes/base.py     # MODIFY: Recipe gains cost params (impact_cost coefficient + maker-fill haircut), default = calibrated (from costs.py); fees_only=False default.
├── scaffold.py         # MODIFY: exchange_kwargs(recipe) adds impact_cost + folds the maker-fill haircut into open/close_cost; a fees_only path reverts to the raw fee_preset + impact_cost=0.
└── command.py          # MODIFY: add `--fees-only/--no-fees-only` flag (default off) → threads to exchange_kwargs; flip a cost-model marker in the report/stdout/run_meta when fees-only.
tests/
├── test_experiment_costs.py    # NEW: COST_CALIBRATION shape; the tier-resolver; realistic vs fees-only exchange_kwargs assembly (impact_cost present/zero; haircut applied/not).
├── test_calibrate_execution.py # NEW: the calibration estimators on a tiny synthetic aggTrades fixture (slippage-vs-size fit; fill-rate/spread estimate); idempotent re-run.
├── test_experiment_scaffold.py # EXTEND: exchange_kwargs realistic-default vs fees-only.
├── test_experiment_command.py  # EXTEND: --fees-only flag parsing + threading + marker; default = realistic.
README.md                       # MODIFY: Usage — the `--fees-only` flag + a note that calibrated costs are the default.
```

## Calibration methodology (pinned)

- **Tiers** by median daily $-volume over the sample: deep (`BTCUSDT`/`ETHUSDT`), mid (`SOLUSDT`/`LINKUSDT`/`ATOMUSDT`), thin (`PEPEUSDT`) — the exact buckets confirmed at calibration from the sample's measured volumes.
- **Slippage `c`:** for trades (or synthetic order-size buckets) of size `q` within a bar, measure realized impact = (execution VWAP vs the bar's reference/close price) in bps; regress impact against `(q$ / bar$-vol)²` to recover `c` per tier; report tier `c`s + whether they're materially different (→ single vs tiered).
- **Maker-fill `f`, spread `s`:** estimate `s` from the bid/ask implied by `is_buyer_maker` transitions; estimate `f` as the fraction of the strategy's typical day-close order size that would rest-and-fill within the bar vs cross — a documented daily-granularity proxy. The haircut uses `(1−f)·(s/2 + taker_premium)` where `taker_premium = taker_fee − maker_fee` for the active `fee_preset`.

## Re-measure & verdict

For each recipe: run the multi-seed holdout **calibrated-default** and **`--fees-only`** at `--seeds 16 --deterministic`. Record, per recipe, the holdout distribution (ending value, Sharpe, PSR) for both and the **net-P&L haircut** = how far realistic sits below fees-only (against the seed-noise band). Expected: realistic is uniformly lower (slippage + fill penalty drag returns); the magnitude — and whether it scales with turnover/thin-book exposure — is the headline. Verdict → `docs/iterations-history.md`; `T0004` → resolved.

## Scope & deferred

- **In:** the calibration script + `costs.py` constants; the slippage `impact_cost` + maker-fill-haircut wiring (recipe params + `exchange_kwargs`); the `--fees-only` opt-out; the all-recipe re-measure + verdict; `T0004` → resolved.
- **Subsumed:** the iter-12 parametric "12 bps + size×volume" term (fulfilled by the calibrated `impact_cost`).
- **Out (parked):** a custom executor with explicit per-order fill probability + non-fill carry-over (the high-fidelity alternative to the haircut); aggTrades-derived microstructure **features** (a feature handler, not `T0004`).
- **Untouched:** the data acquisition layer (the aggTrades mirror is read-only here); the qlib `data-dir`/dataset; the recipes' models/labels/signals; the `--pit-universe` lever (orthogonal — composes).

## Closeout tasks (authored when the work is real)

- Run `calibrate_execution.py` on the real aggTrades sample → record the calibrated `(c, f, s)` per tier + the single-vs-tiered finding; commit the `COST_CALIBRATION` constants.
- Run all recipes calibrated-default vs `--fees-only` (`--seeds 16`) → the per-recipe execution-cost haircut verdict.
- Flip `T0004` → `resolved` (front-matter + `git mv` to `docs/open-topics/archive/` + index link; the verdict in the topic).
- README `## Usage`: the `--fees-only` flag + the calibrated-costs-default note.
- iter-19 iterations-history entry (the cost model, the calibration, the haircut verdict).
