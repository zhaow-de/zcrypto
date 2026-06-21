# Funding-carry feature — Design

**Iteration:** iter-20
**Advances open-topic:** `T0010` (non-OHLCV features) — the **funding portion** lands here (the funding *feature* + recipe + edge-test); on-chain / order-book remain, so `T0010` stays **`partial`**.
**Depends on:** iter-15 (the `$funding` qlib field), iter-13 (the `CrossAssetProcessor` feature-handler pattern + `feature_config` seam), iter-14 (the multi-seed holdout A/B), iter-19 (realistic costs are now the default).

## Context — what

Alpha158/360 and the iter-13 cross-asset handler are all derived from daily OHLCV. Perpetual **funding** — the cost of leveraged positioning — is a different information source (carry + crowding) that OHLCV structurally lacks. iter-15 made Binance USDT-perp funding a first-class qlib field `$funding` (daily-summed carry, same-day-aligned with `$close`). This iteration turns that data into a **feature** and runs the genuinely-new-signal edge test the funding stream was built for.

## Why this matters

Research §5/§14: funding rates reflect leveraged crowding and the cost of carry, and can precede price reversions — information a competitor without derivatives data cannot replicate. This is the cleanest "different information" experiment after the OHLCV family (Alpha158/360/cross-asset) is exhausted. A positive result is a real edge; a null result is itself informative (funding adds nothing beyond OHLCV cross-sectionally, on a daily horizon).

## Established pattern (reused verbatim)

The iter-13 `CrossAssetProcessor` (`cli/experiment/features/cross_asset.py`) is the template: a pure feature function (`cross_asset_features(wide_panel) -> (datetime, instrument) frame`) + a `Processor` subclass whose `__call__(df)` loads the needed raw panel via a thin `_load_close` seam over `D.features`, computes features, reindexes to `df.index`, and appends each as a `("feature", <name>)` column. Wired **first** in a recipe's `infer_processors` so the subsequent `RobustZScoreNorm` normalizes the appended columns on the same scale as Alpha158's native factors; `Fillna` then handles any NaN. The funding feature mirrors this exactly.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **`FundingRateProcessor`** in a new `cli/experiment/features/funding.py`, mirroring `cross_asset.py`: a pure `funding_features(funding_panel) -> frame` + the `Processor` subclass + a `_load_funding(insts, start, end)` seam (mirror of `_load_close`, querying `$funding`). Reuse the `_stack` helper pattern. | Maximal reuse of the proven iter-13 pattern; the pure function is qlib-free and unit-testable without redis/qlib (as `cross_asset_features` is). |
| 2 | **Focused carry feature set (5 columns), all leak-safe (current + past funding only):** `funding_level` (raw daily carry), `funding_z` (per-instrument z-score vs a trailing window, W=30), `funding_csrank` (per-date cross-sectional percentile rank across the universe), `funding_ma` (per-instrument 7-day rolling mean — persistent regime), `funding_chg` (per-instrument 7-day change). | Covers level + extremity + relative crowding + regime + trend without overfitting a small universe (matches crossasset's "handful of focused features"). Cross-sectional rank is the classic carry-ranker signal. Trailing windows / same-day cross-section only → no forward leakage (guarded by a leak-safe test, as cross-asset has). |
| 3 | **Two recipes**, both keeping `feature_config`=Alpha158: **`funding_steady`** (steady's exact book/model/label/universe/fees + `FundingRateProcessor` prepended first) — the clean isolation; **`funding_crossasset_steady`** (crossasset_steady's book + **both** `CrossAssetProcessor` and `FundingRateProcessor` prepended, before `RobustZScoreNorm`) — the stacking test. | `funding_steady` vs `steady` isolates funding's marginal contribution (only the funding columns differ). `funding_crossasset_steady` vs `crossasset_steady` tests whether funding stacks with the current-best feature add. Book held constant → a clean falsifiable A/B. |
| 4 | **Edge test = multi-seed (`--seeds 16 --deterministic`) holdout A/B**, judged on the **cost-adjusted Sharpe** — NOT `ending_value`. | Two A/Bs: `funding_steady` vs `steady`; `funding_crossasset_steady` vs `crossasset_steady`. Funding "wins" only if the paired Sharpe gain clears the seed-noise band (iter-14 discipline). **Per `T0015`, the holdout `ending_value` is gross (pre-cost) and cost-insensitive — the verdict must read the cost-adjusted Sharpe.** Realistic costs are the default (iter-19), so the A/B is net-of-realistic-cost. |
| 5 | **Coverage:** the traded 19 majors all have `$funding` coverage (iter-15); reference/pre-perp pairs carry NaN funding. The processor appends the raw funding columns with NaN where `$funding` is absent; `RobustZScoreNorm` + `Fillna` handle them (identical to cross-asset's NaN handling). | No special-casing needed — the existing normalization chain absorbs the gaps, and the signal is populated where it's traded. |

## Component file tree

```
cli/experiment/
├── features/funding.py   # NEW: funding_features(funding_panel, *, z_window=30, ma_window=7, chg_window=7) -> frame;
│                         #      _load_funding(insts, start, end) (mirror _load_close, queries $funding);
│                         #      FundingRateProcessor(Processor) appending the 5 columns. Reuses the _stack pattern.
├── recipes/funding_steady.py            # NEW: steady book + FundingRateProcessor first in infer_processors.
└── recipes/funding_crossasset_steady.py # NEW: crossasset book + CrossAssetProcessor + FundingRateProcessor (both before the norm).
tests/
├── test_funding_feature.py   # NEW: funding_features on a synthetic funding panel — expected 5 columns; index names
│                             #      ("datetime","instrument"); leak-safe trailing (truncating the tail doesn't change earlier rows);
│                             #      finite after warmup; no inf; cross-sectional rank in [0,1]; NaN-funding rows handled.
└── test_experiment_recipe.py # EXTEND: funding_steady / funding_crossasset_steady resolve + wire FundingRateProcessor
                              #         (and crossasset's processor for the combo) first in infer_processors; book matches the base recipe.
README.md                     # MODIFY: Usage — list the two new recipes (the recipe table / examples).
```

## Feature definitions (leak-safe; pure function over a wide `date × instrument` funding panel)

- `funding_level` — the raw `$funding` value (current day's daily carry).
- `funding_z` — `(f - f.rolling(30).mean()) / f.rolling(30).std()` per instrument (trailing).
- `funding_csrank` — per-date cross-sectional percentile rank of `f` across instruments (same-day; `rank(pct=True)` across columns).
- `funding_ma` — `f.rolling(7).mean()` per instrument (trailing).
- `funding_chg` — `f - f.shift(7)` per instrument (trailing).

All use only current/past funding or the same-day cross-section → no forward leakage. NaN where `$funding` is absent (reference/pre-perp pairs); downstream `Fillna` resolves them.

## A/B & verdict

For each pair, run the multi-seed holdout at `--seeds 16 --deterministic`: `funding_steady` + `steady`; `funding_crossasset_steady` + `crossasset_steady`. Record the per-seed **cost-adjusted Sharpe** distribution and the **paired** difference (funding-variant minus base, same seed) — the clean measure of funding's marginal contribution. Verdict: funding carries edge beyond OHLCV iff the paired Sharpe gain clears the seed-noise band; likewise whether it stacks with cross-asset. Either outcome (edge or null) lands in `docs/iterations-history.md`.

## Scope & deferred

- **In:** the `FundingRateProcessor` + the 5-feature `funding_features`; the two recipes; the two multi-seed A/Bs + the verdict; the unit tests; the README recipe list.
- **Out (T0010 remainder):** on-chain and order-book features (separate streams/iterations).
- **Out (deliberate, for a clean isolation):** any funding-specific model/label/universe change — the book is held constant so the A/B isolates the funding features.
- **Untouched:** the data layer (`$funding` is read-only here via `D.features`); the cost model (iter-19 realistic-default applies to both arms); the scaffold/cpcv/multiseed harness.

## Closeout tasks (authored when the work is real)

- Run both A/Bs (`--seeds 16`, redis up) → record the paired cost-adjusted-Sharpe verdict (funding edge? stacks?).
- Advance `T0010` (funding feature → done; on-chain/order-book remain → stays `partial`): update the `## Done so far` / `## Suggested next steps`.
- README `## Usage`: the two new recipes.
- iter-20 iterations-history entry (the feature, the two recipes, the funding-edge verdict).
