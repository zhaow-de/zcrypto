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

Reality check (iter-10): the **listing side is already handled** — qlib returns
rows only where data exists, so a pair is never traded before it listed; the bias
is the **universe selection** (today's survivors). We hold **zero delisted-pair
data**, and `zcrypto data delist` _deletes_ a pair's history (`cli/data/pipeline.py`),
so a real fix must first acquire historically-delisted pairs. iter-10 added an
honest survivorship caveat to the experiment outputs (report title, stdout,
`run_meta.json` `caveats`) but changed no results.

## Suggested next steps

- Acquire historically-delisted Binance USDT pairs' data (enumerate
  `data.binance.vision` for symbols whose daily-kline archives end before today)
  so the panel is survivorship-free.
- Change `zcrypto data delist` to retain-with-end-date (or keep a delisted
  registry) instead of deleting history.
- Build point-in-time membership over the expanded panel (qlib market-name
  instruments file honoring per-symbol listing/delist dates) and feed it to the
  experiment.
- Add a delisting-loss assumption (forced liquidation at the last close / a
  size-scaled haircut).
- Re-measure the baseline's edge under the point-in-time universe vs the current
  survivor universe.
