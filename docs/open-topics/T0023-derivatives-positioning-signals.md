---
status: open
---

# Derivatives-positioning signals — follow-ups after basis-froth-timing

## Context — what

iter-38 ingested the free Binance futures derivatives streams (`$oi`, `$oi_value`, `$ls_top`,
`$ls_global`, `$taker_ratio`, `$basis`) as qlib fields. iter-39 ran the first signal — a perp-spot-basis
"froth" **de-risk timing overlay** composed on `beta_null` (high cross-sectional median `$basis` → cut
exposure) — and it was **refuted** (mean delta-vs-null −0.208: the de-risk fires in bulls and cuts upside;
high basis persists through bull continuation rather than flagging reversal at the daily horizon). This
topic tracks the remaining derivatives-positioning signal forms to test before the channel is judged.

## Why this matters

Derivatives-positioning is the orientation's (`docs/research/03.phase2-orientation.md` §3 #2) strongest
genuinely-**free new-information** Channel-A bet — positioning (funding / OI / basis / long-short) is a
distinct information source from price/OHLCV. One signal *form* failing (a binary market-timing gate) is
not the same as the channel being absent: the most-replicated derivatives edges are **cross-sectional**
(rank coins by crowding), which iter-39 did not test. The reusable `froth_*` overlay + the `basis_froth`
recipe are the apparatus for the variants below.

## Findings so far

- iter-39: basis as a **binary market-timing de-risk gate** (cross-sectional median `$basis` z > 1.5 → cash,
  composed on `beta_null`) is **refuted** (mean delta −0.208; hurts in the 2024/2025 bull years; the
  BTC-200d gate already handles the bear, so the overlay only adds harmful de-risking). Spec `00036`.
- iter-40: basis as a **cross-sectional crowding TILT** (down-weight high-`$basis` coins, `w *= exp(−k·z)`,
  composed on the inverse-vol basket) is **also refuted** (mean delta −0.183; worst in the 2024 bull −0.44).
  Down-weighting crowded coins underperformed inverse-vol — high basis behaves like a **demand/momentum**
  proxy (keeps running) rather than a contrarian-reversal one at the daily horizon. Spec `00037`. **So
  `$basis` is exhausted across BOTH forms (timing gate + cross-sectional tilt).** The reusable `crowding_*`
  tilt + `froth_*` overlay remain available for `$oi`/`$ls_*` variants.

## Suggested next steps

- **Cross-sectional basis/funding crowding TILT (the immediate next, iter-40):** rank the universe by
  `$basis` (and/or `$funding`) per rebalance and re-weight the basket toward the under-crowded
  (backwardated / low-funding) names and away from over-crowded (high-premium / high-funding) ones — the
  orientation's core derivatives-positioning form. A *selection/weighting* signal, NOT a market-timing
  gate (which iter-39 showed fails). A/B vs `beta_null`'s inverse-vol weighting.
- **OI-price divergence:** rally on falling OI = weak (fade) / rally on rising OI = confirmed (trend) —
  a price×OI joint signal, as a tilt or a per-asset filter.
- **Graded / sign variants of the froth signal:** a *graded* de-risk scale (not binary cash), and the
  *backwardation* side (low/negative basis → risk-on) — cheap variants of the now-built `froth_*` overlay.
- **`$taker_ratio` / long-short contrarian:** extreme taker buy/sell or top-trader L/S as a contrarian tilt.
- **Honesty caveat:** funding is **decaying** (orientation: full-sample Sharpe ~6.4 → negative by 2025), so
  prefer `$basis` / `$oi` as the fresher probes; read cost-adjusted OOS verdicts, not gross.
- **Kill condition (parked — human ratifies):** if the cross-sectional tilt AND OI-divergence both fail to
  beat the null, treat derivatives-positioning as a dead Channel-A sub-bet and redirect to BTC→alt lead-lag
  (`T0020`) — a high-stakes pivot for an attended session, not the loop.
