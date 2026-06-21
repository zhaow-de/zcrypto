---
status: partial
priority: medium
---

# Pluggable feature handler

## Context — what

The experiment scaffold (`scaffold.py`, `cpcv.py`) hardcodes `Alpha158` as the
feature handler for every recipe. Making the feature handler recipe-selectable —
the way `strategy_config` (iter-12) made the strategy class pluggable — would
allow recipes to select `Alpha360`, a custom crypto feature set (momentum,
funding-rate factors, cointegration-deviation signals per research §5), or any
future handler without touching the scaffold.

## Why this matters

`Alpha158` is a generic equity factor library; crypto has distinctive signals
(funding rates, cross-exchange cointegration deviations, on-chain volume proxies)
that `Alpha158` does not capture. Research §5 calls out momentum, funding, and
cointegration-deviations as the primary alpha sources for the cross-sectional
ranker. Locking the handler in the scaffold forces all feature experimentation
through ad hoc scaffold edits rather than clean recipe-level composition.

## Findings so far

Identified during iter-12 scoping (spec `00011`); deferred to this topic. The
strategy-seam migration (`strategy_config`) in iter-12 established the pattern:
a recipe-level `dict` field that the scaffold passes to `init_instance_by_config`
at runtime. A `feature_config` field would follow the same pattern. References:
research §5, spec `00011` (decisions table: "pluggable feature handler" listed
as deferred).

## Done so far

Shipped in iter-13 (spec `00012`, branch `feat/pluggable-feature-handler`):

- **`feature_config` seam** — `Recipe.feature_config = {class, module_path}` added to
  `cli/experiment/recipes/base.py`; defaults to Alpha158. `scaffold.handler_config()`
  helper builds the full qlib handler config dict from `feature_config` + instruments +
  segments + `handler_kwargs`; used in both `scaffold.py` and `cpcv.py:_materialize_span`,
  replacing the previously hardcoded `Alpha158` dict.
- **Benchmark migration** — `skeleton`, `steady`, and `regime_steady` migrated
  behavior-preservingly to explicit `feature_config`; a regression test asserts the built
  handler config is unchanged.
- **`Alpha360` wired** — `alpha360_steady` recipe: `steady`'s book + qlib built-in `Alpha360`
  handler, exercising the seam end-to-end.
- **Custom cross-asset handler** — `cli/experiment/features/cross_asset.py`: pure
  `cross_asset_features(panel, ...)` function + `CrossAssetProcessor` qlib wrapper;
  surfaced via the `crossasset_steady` recipe (Alpha158 + BTC-anchored relative
  strength / rolling beta / lead-lag / cointegration-deviation / cross-sectional rank).

The edge verdict for `alpha360_steady` and `crossasset_steady` is recorded separately in
`docs/iterations-history.md` (iter-13 entry).

## Suggested next steps

- Explore **learned / embedding feature layers** (e.g. autoencoder on OHLCV, transformer
  tick-level features) as `feature_config`-selectable handlers.
- Wire in other qlib built-in handler classes beyond Alpha158/360 (e.g. `Alpha101`) to
  complete the built-in survey.
- Non-OHLCV features (funding-rate / on-chain / order-book) require a new data source —
  tracked in `T0010`.
