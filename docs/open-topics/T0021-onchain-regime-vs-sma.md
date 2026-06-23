---
status: partial
---

# On-chain regime overlay vs the 200d-SMA gate (BTC/ETH market-timing)

## Context — what

Phase 1 imagined on-chain data as "the frontier" (`T0010`). The Phase 2 on-chain research,
consolidated in [`docs/research/03.phase2-orientation.md`](../research/03.phase2-orientation.md),
demotes it: the only on-chain signals with rigorous out-of-sample evidence are **BTC/ETH
cycle-valuation (MVRV-Z, NUPL) and stablecoin / exchange flows**, and they are usable **only as
a market-wide regime / flow overlay**, NOT as a per-alt cross-sectional signal (memecoins and
young L2 tokens have structurally meaningless holder metrics). So on-chain competes with the
existing 200d-SMA regime gate for the *same* timing job. This topic is the falsifiable
head-to-head: **can an on-chain regime signal beat the 200d-SMA gate OOS, net of costs?**

## Why this matters

The decisive comparison — on-chain market-timing vs simple trend-following, net of costs — is
**unpublished**; the literature shows on-chain (MVRV-Z) beats buy-and-hold and trend beats
buy-and-hold, but nobody has cleanly shown on-chain beats trend. The disciplined prior is
**comparable, not better**, with possible marginal gain from *combining* them. This is the single
highest-value use of on-chain data for the project, and it is cheap to test (free data first), so
it resolves the `T0010` on-chain question without recurring spend.

## Findings so far

- None yet (Phase 2). `T0010` already shipped the funding stream and the funding *feature*
  (modest, defensive, gate-redundant edge — iters 15/20); this topic is the on-chain *regime*
  use, which is distinct from the funding feature.
- Coverage reality: BTC's UTXO model gives the richest metrics (SOPR / HODL waves / realized cap
  / MVRV); ETH and account-based chains give fewer; alts/memecoins give ~none → on-chain is a
  BTC/ETH-level signal applied across the basket, never a clean per-alt signal.
- **iter-46 DATA DISCOVERY (corrects the plan):** the keyless Coin Metrics **community** API does
  NOT serve the cycle-valuation metrics — `CapRealUSD` (→ MVRV-Z/NUPL) and `TxTfrValAdjUSD` (→ NVT)
  return `forbidden`. So MVRV-Z/NUPL/NVT need a **credentialed** plan → **parked** (the credentialed-
  data item, not auto-set-up). Keyless BTC metrics that ARE available: `CapMrktCurUSD` (market cap),
  `AdrActCnt` (active addresses), `TxCnt`, `HashRate`, `SplyCur`.
- **iter-46 result (keyless NVM proxy):** the best keyless valuation proxy, NVM =
  `log(CapMrktCurUSD / AdrActCnt²)`, as a de-risk regime overlay (cash when NVM-z extreme-high) is
  **REFUTED (mean delta-vs-`beta_null` −0.414)** — it cashed during 2023's recovery (−1.155) and the
  2024 bull (−0.528); high NVM during a bull is momentum, not a top. This fits the night's broader
  finding that **fade-strength signals lose** in the momentum-dominated 2022-2025 sample (see
  iterations-history iter-46). The keyless-NVM failure does **not** condemn credentialed MVRV-Z (a
  better metric); that head-to-head remains the open question.

## Done so far

- iter-46 (spec `00043`, PR pending): built `cli/data/onchain.py` (keyless Coin Metrics fetcher + NVM
  cache) + an `onchain_regime` de-risk overlay on `VolWeightedRegimeStrategy` + the `onchain_regime`
  recipe; A/B vs `beta_null` → **NVM regime REFUTED (−0.414)**. The reusable fetcher/overlay remains for
  any future on-chain work. **Discovered** that the strong cycle-valuation metrics (MVRV-Z/NUPL/NVT) are
  NOT keyless → the credentialed head-to-head is parked.

## Suggested next steps

Still open (the keyless NVM probe is done/refuted above; the real cycle-valuation head-to-head needs
credentialed data → **parked for an attended session**):

- **PARKED (credentialed-data step):** obtain MVRV-Z / NUPL — either Coin Metrics PRO, CryptoQuant
  Professional (~$109/mo, cancel before renewal), or compute realized-cap from Google BigQuery public
  blockchain datasets (free but heavy). This is the credentialed-data item the loop does NOT set up
  autonomously. The `onchain_regime` overlay + fetcher already exist (iter-46) — only the *better
  metric* (realized-cap-based MVRV-Z) is missing.
- **Then the real head-to-head:** MVRV-Z + NUPL (+ exchange-reserve / stablecoin flows) regime vs the
  200d-SMA gate — three-way A/B (on-chain alone, SMA alone, AND-combination) on `zcrypto stress`.
- **Success bar (adopt on-chain):** beats the SMA on OOS Calmar / Sharpe by a margin that survives
  walk-forward AND is not a handful of cycle turning points. **Kill:** if it only ties, keep the SMA.
- **Lower-priority keyless variant (reversible, no spend):** the available keyless metrics (active-address
  momentum, hash-rate, tx-count) as a *confirmation* (not fade-strength) signal — but the iter-46 refutation
  + the momentum-dominance finding make this low-EV; prefer the credentialed MVRV-Z head-to-head.
