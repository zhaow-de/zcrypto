---
status: open
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

## Suggested next steps

- Add a `feature_config` field to `Recipe` (mirroring `strategy_config` /
  `model_config`) that accepts a full `{class, module_path, kwargs}` dict.
- Refactor `scaffold.py` and `cpcv.py` to build the dataset handler from
  `feature_config` instead of hardcoding `Alpha158`.
- Migrate `skeleton`/`steady`/`regime_steady` to explicit `feature_config`
  (behavior-preserving; `Alpha158` with their current kwargs).
- Add a recipe using `Alpha360` and compare factor richness vs `Alpha158`
  on the same universe.
- Prototype a custom crypto feature module (funding rate, cointegration
  deviation, cross-pair momentum) and wire it in as a recipe-selectable handler.
