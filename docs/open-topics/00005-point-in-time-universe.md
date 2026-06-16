---
status: open
priority: medium
---

# Point-in-time universe / survivorship bias

## Context — what

The experiment skeleton (spec `00006`) trades the currently-known 19-pair USDT
universe across all of history. A point-in-time universe would include each coin
only from its actual listing and exclude/handle delistings as they happened.

## Why this matters

Research §3/§12 — Binance delists ~20–50 spot pairs/quarter (49 in Q1-2025); a
"currently listed" universe inflates historical results via survivorship, and a
delisted coin held in inventory can drop 50–90% before liquidation.

## Findings so far

Deferred from the experiment skeleton (spec `00006`). The `cli/data` layer
already records per-instrument listing ranges and has delist/rename handling
(partial mitigation), but the skeleton's universe selection isn't point-in-time.
References: research §3, §12; existing `cli/data` delist/rename.

## Suggested next steps

- Build point-in-time membership (include from listing, drop on delist) and feed
  it to qlib instrument filtering.
- Add a delisting-loss assumption.
- Re-measure the baseline's edge under PIT vs current-universe.
