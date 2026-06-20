---
status: partial
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

## Done so far

**Survivorship-free data substrate landed (iter-16, spec `00015`).** The dataset now
includes 10 ever-top-25 USDT majors that blew up / faded out of the current 19, acquired
with their real listing→delisting ranges so the panel is no longer survivor-only:
`DASHUSDT`/`ZECUSDT`/`QTUMUSDT`/`ICXUSDT` (full history), `FTTUSDT` (full, with the
FTX-collapse suspension `2022-11-16..2023-09-21` carried as NaN), and the delisted
`WAVESUSDT`/`OMGUSDT`/`XEMUSDT` (archive-only to 2024-06-17), `BTGUSDT` (..2022-10-24),
`NANOUSDT` (..2022-01-24). The RECON corrected the original premise: Binance keeps
delisted symbols in `exchangeInfo` as `status="BREAK"` (not removed), so the existing
`download` acquires them archive-only — no not-in-`exchangeInfo` path was needed.
Two supporting changes shipped: `delist` was **renamed → `drop`** (a pure pair-removal
tool — market delistings are now *retained*, not deleted, removing the survivorship
footgun), and an opt-in **`--allow-interior-gaps`** download flag NaN-fills interior 404s
(trading halts) so halted blow-ups acquire honestly without weakening the regular
download. qlib returns each pair's rows only within its real range → point-in-time
membership is free the moment a recipe's `universe` includes them.

## Suggested next steps

- **Expand each `recipe.universe` to include the delisted majors** (PIT membership — qlib
  already honors the per-symbol ranges; the universe tuples just gain the symbols).
- **Add a delisting-loss assumption** — liquidate a held position at its last available
  close when a pair delists (the klines capture the crash; FTT's suspension is NaN).
- **Re-measure** the baseline on the PIT universe vs the survivor universe to quantify the
  survivorship inflation → flips `T0005` → resolved. (The systematic multi-window/crisis
  sweep is `T0007`, now data-enabled by this substrate.)
- (Stretch) acquire the Terra collapse (`LUNC`/`USTC`) — deferred here for the
  LUNA→LUNC/Luna-2.0 symbol-reuse complication.
