---
status: open
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

## Suggested next steps

- **Data (free-first):** Coin Metrics Community (pre-computed BTC/ETH metrics, CSV, no key) +
  Google BigQuery public blockchain datasets (raw chains, CC-BY, offline-reusable) + Flipside;
  build a reusable historical on-chain panel offline. Pay for **one month of CryptoQuant
  Professional (~$109 — NOT the $39 Advanced, which lacks the bulk Data API)** ONLY if a specific
  entity-adjusted metric is missing *and* shows preliminary promise; cancel before renewal.
- **On-chain regime signal:** combine MVRV-Z + NUPL (cycle valuation) + exchange-reserve trend +
  stablecoin dry-powder (SSR / stablecoin net-inflows) into a BTC exposure signal.
- **Three-way A/B on the `zcrypto stress` harness, net of costs:** (i) on-chain gate alone,
  (ii) 200d-SMA gate alone (the Phase 1 baseline), (iii) AND-combination / exposure-scaling
  hybrid.
- **Success bar (adopt on-chain):** beats the SMA on OOS Calmar / Sharpe by a margin that
  survives walk-forward *and* is not explained by a handful of cycle turning points. **Kill:** if
  it only ties the SMA, keep the simpler SMA and do **not** pay to re-pull on-chain data.
- Wire on-chain metrics as qlib fields / a feature handler via the existing pluggable seam (as
  *inputs* to a spot long/cash strategy, never as traded instruments).
