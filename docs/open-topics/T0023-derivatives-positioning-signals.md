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
- iter-41: **OI-price divergence** as a cross-sectional confirmation tilt (`oi_divergence_tilt`: up-weight
  coins where price + OI move together, down-weight weak price↑/OI↓ rallies) is **NEUTRAL** — mean delta
  **+0.008** (helped 2024 +0.41, hurt 2023 −0.33; per-window CIs straddle 0). Doesn't clear the success bar
  (not adopted), but it's the **first non-negative** derivatives signal and the **most promising** (vs basis's
  clear −0.18/−0.21). Spec `00038`; the `oi_divergence`/`_apply_cross_sectional_tilt(sign=+1)` machinery is
  reusable. **The shelve-derivatives kill-condition is NOT met** — OI-divergence is a live thread to refine.
- iter-42: **directional** OI-divergence (`oi_div_directional`: confirmation = `oi_chg` for up-price coins,
  NaN/neutral for down-price — stops up-weighting confirmed downtrends) is **NEUTRAL (+0.010, ~tied with
  iter-41)**. It *validated* the directional hypothesis — 2023 improved to −0.086 (from −0.33) — but 2025
  worsened, so net unchanged. **Cross-iteration:** OI-confirmation **consistently helps 2024** (+0.31/+0.41)
  but is flat/negative in 2023/2025 → a real **strong-bull-regime** effect, not all-weather. Spec `00039`;
  the directional form supersedes iter-41's symmetric one. Still no CI-clearing edge.
- iter-43: **smart-money L/S divergence** (`smart_money_tilt`: up-weight high `$ls_top/$ls_global` = top-traders
  more long than retail) is **slightly NEGATIVE (−0.066)**. "Follow smart money" hurt in the 2024 bull (−0.24)
  — the smart-money-long coins were the laggards (retail crowded the momentum winners). Account positioning
  adds no edge. Spec `00040`. **Scorecard (5 signals):** basis ×2 (−0.21/−0.18 dead), OI ×2 (+0.008/+0.010
  neutral/bull-only), L/S (−0.066) — no clear edge; OI's 2024 effect is the lone positive.
- iter-44: **strong-trend-gated** OI tilt (apply only when BTC >25% above 200d) **backfired** (−0.014, worse
  than ungated +0.010) — the gate cut the 2024 benefit (excluded early-2024) more than it shaved the
  2023/2025 drags. OI-confirmation is **not robustly gateable**. Spec `00041`. **Single-factor derivatives
  sweep COMPLETE (6 signals): no robust edge; best ~neutral (directional OI +0.010). Shelve-call now
  well-evidenced (parked).** Next genuinely-untried reversible angle: an **ML model combining all the
  derivatives fields as features** (vs hand-crafted single-factor tilts) — `$taker_ratio` folds in as one feature.
- iter-45: **derivatives ML features** (`DerivativesProcessor` + `derivatives_steady` = `steady` + the 26 leak-safe
  derivatives feature columns) is **MARGINAL vs steady (+0.049, only 2023 CI clears 0) but SUB-PASSIVE** — its own
  long-only OOS Sharpes (−0.95/1.52/0.76/−0.58, mean ≈ −0.06) are far below `beta_null`'s ~0.38. The features
  carry a weak, regime-specific (2023) ML signal but don't rescue the sub-passive `steady` base. Spec `00042`.
  **Derivatives channel COMPREHENSIVELY TAPPED (single-factor tilts + multi-factor ML): nothing beats `beta_null`.
  Shelve-call comprehensively evidenced — parked for the human.** `DerivativesProcessor` is reusable for future ML.

## Suggested next steps

- **Refine OI-divergence (the live thread, the immediate next):** iter-41's OI-divergence tilt is NEUTRAL
  (+0.008; helped 2024, hurt 2023) — the most promising probe. Sweep `oi_div_lookback` / `oi_div_tilt_k`,
  **regime-condition** it (the 2024-helps / 2023-hurts split suggests a bull/bear dependence — e.g. apply the
  tilt only when the BTC-200d gate is risk-on), or combine the confirmation score with price momentum. Reuses
  the `oi_divergence` machinery. A/B vs `beta_null`.
- **Graded / sign variants of the froth signal:** a *graded* de-risk scale (not binary cash), and the
  *backwardation* side (low/negative basis → risk-on) — cheap variants of the `froth_*` overlay. (Lower
  priority — basis was refuted in both forms.)
- **`$taker_ratio` / long-short contrarian:** extreme taker buy/sell or top-trader L/S as a contrarian tilt.
- **Honesty caveat:** funding is **decaying** (orientation: full-sample Sharpe ~6.4 → negative by 2025), so
  prefer `$oi` / `$basis` as the fresher probes; read cost-adjusted OOS verdicts, not gross.
- **Kill condition (parked — human ratifies), updated after iter-41:** `$basis` is refuted in both forms, but
  OI-divergence is **neutral/promising, not failed**, so the shelve-call is **NOT yet triggered**. Only if the
  *refined* OI-divergence (regime-conditioned / tuned) also fails to clear the bar would
  "shelve derivatives-positioning and redirect to BTC→alt lead-lag (`T0020`)" be evidenced — a high-stakes
  pivot for an attended session, not the loop.
