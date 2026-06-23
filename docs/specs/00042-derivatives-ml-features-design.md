# iter-45 — Stage-2: derivatives ML features (`derivatives_steady`) (design)

**Goal:** test whether an **LGBModel** can extract cross-sectional alpha by **combining the derivatives
fields as features** (non-linear / interaction), where the hand-crafted single-factor tilts (iter-39–44,
all ~neutral/negative) could not. **Success bar:** `derivatives_steady` beats its baseline `steady` (and
ideally `beta_null`) on cost-adjusted OOS Sharpe with a CI clearing 0. Decisions `.tmp/decisions.md` iter-045;
the multi-factor closeout of `T0023`.

## Context

The single-factor derivatives sweep is tapped (basis ×2 dead, OI ×3 neutral, L/S negative). The one untried
*reversible* angle is to let the model learn a multi-factor combination — exactly the `funding_steady`
pattern (= `steady` + `FundingRateProcessor` + LGBModel), extended from `$funding` to all six derivatives
fields. Modest prior (the single factors are individually weak, and Phase-1 found OHLCV-ML — `steady` —
doesn't robustly beat the simpler defensive recipes, per `T0018`), but it's the proper combination test and
cleanly closes the derivatives channel.

## Design — mirror `FundingRateProcessor`

- **`DerivativesProcessor`** (`cli/experiment/features/derivatives.py`, mirroring
  `cli/experiment/features/funding.py`): a pure `derivatives_features(panels)` that, for each of `$oi`,
  `$oi_value`, `$ls_top`, `$ls_global`, `$taker_ratio`, `$basis`, appends **leak-safe** feature columns —
  per field: **level**, **change** (`/ shift(n) − 1` or a diff for the ratios), **cross-sectional rank**
  (`rank(axis=1, pct=True)`, same-day cross-section), and **z vs own history** (trailing rolling
  mean/std) — plus the two derived signals the single-factor work flagged as worth combining:
  `oi_confirm = sign(price_chg)·oi_chg` (using `$close`) and `smart_div = $ls_top/$ls_global`. Every column
  uses only current/past data (trailing rolling/shift) or the same-day cross-section (rank) — NO look-ahead,
  exactly like `funding_features`. A `Processor` subclass loads the panels via `D.features` and appends them
  as `("feature", <name>)` columns, used as the FIRST `infer`/`learn` processor (so `RobustZScoreNorm`
  normalizes them on Alpha158's scale), same wiring as `FundingRateProcessor`.
- **`derivatives_steady` recipe:** `steady`'s book **verbatim** + `DerivativesProcessor` prepended to the
  processors (the ONLY change vs `steady`) — same LGBModel, Alpha158, label, ranking strategy, segments,
  fee, universe. So the A/B isolates the derivatives features' ML contribution.

## Validation

`zcrypto stress --recipe derivatives_steady --null steady` (isolates the features' contribution) → per-window
+ across-window delta + bootstrap CI + CPCV. Also read `derivatives_steady` vs `beta_null` (the yardstick)
from the bundles. Read cost-adjusted, not gross.

## Success / kill

- **Win:** `derivatives_steady` beats `steady` (delta > 0, CI clears 0) AND ideally clears `beta_null` →
  derivatives features add real ML-rankable alpha; next prune the features / tune the model.
- **Null/negative:** the ML model finds no robust alpha in the derivatives features either → **the
  derivatives channel is definitively tapped** (single-factor AND multi-factor ML). Then the parked
  "shelve derivatives-positioning → BTC→alt lead-lag (`T0020`)" call is comprehensively evidenced (still
  parked for the human — `T0020` needs a 1h-bar dataset + intraday harness, out of this loop's scope).

## Testing (TDD)

- **`derivatives_features` unit:** on a small synthetic multi-field panel, the expected columns appear with
  the right values; **leak-safe** — a feature row at d uses only data ≤ d (trailing) or the same-day
  cross-section (rank); NaN where a field is NaN (no perp / pre-launch).
- **`DerivativesProcessor` unit:** appends the columns as `("feature", <name>)`; mirrors the
  `FundingRateProcessor` test.
- **`derivatives_steady` drift-guard:** resolves; identical to `steady` EXCEPT `DerivativesProcessor`
  prepended to the processor lists (assert that's the only delta).
- **stress A/B** — redis-gated.

## Closeout

`docs/iterations-history.md` iter-45 entry with the delta-vs-`steady` (and vs `beta_null`) verdict; update
`T0023`; if negative, record the derivatives channel as comprehensively tapped (single + multi-factor ML)
and restate the parked shelve/pivot call.
