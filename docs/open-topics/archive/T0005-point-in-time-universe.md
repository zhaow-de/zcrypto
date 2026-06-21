---
status: resolved
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

**De-bias lever + Terra acquisition + re-measure landed (iter-18, spec/plan `00017`).** A
`--pit-universe` flag on `zcrypto experiment` expands any recipe's universe to point-in-time
membership (`PIT_ADDITIONS` = the 10 iter-16 majors + Terra `LUNCUSDT`) via a single
`dataclasses.replace` swap, flipping the run's caveat/report marker to "survivorship-free".
The **delisting-loss** needs no code: a recon confirmed qlib **freezes** a held position at
its last close (the mark-to-market loss is captured); redeploying the trapped capital is
parked as [[T0014-force-liquidate-on-delisting]]. The **Terra blow-up** was acquired despite
Binance's `LUNAUSDT` symbol reuse: a one-off `cli/data/scripts/acquire_old_luna.py` fetches
old LUNA bounded at the 2022-05-13 crash (excluding the reused-symbol Luna 2.0), renamed to
its canonical `LUNCUSDT` identity (old-LUNA arc + 118-day NaN gap + Luna-Classic tail to
today; cap verified — 2022-06-15 is NaN, not Luna 2.0's $2.53).

## Resolution (iter-18)

All 5 recipes were re-measured **survivor vs `--pit-universe`** on the 16-seed deterministic
holdout (test = 2025-01-01 .. 2026-06-15). The point-in-time universe is **equal-or-better**
than the survivor universe (median ending-value ratio PIT/survivor 1.04×–1.43×, within the
seed-noise band for 4 of 5) — **no survivorship inflation**. The reason is concrete: every
acquired blow-up crashed *before* the test window (LUNA/FTT/NANO/BTG 2022; OMG/WAVES/XEM
faded by mid-2024), so the 2025+ holdout never holds a coin **through** its crash; the PIT
universe only enriches *training* data and adds a few quiet faded low-caps as 2025 candidates.
(Caveat: the `--seeds` multi-seed holdout runs the base strategy, so `regime_steady` ≡ `steady`
— walk-forward/regime gating isn't exercised on that path.)

**Verdict:** our current eval window is *not* survivorship-inflated **because it postdates the
collapses**. The de-bias capability (survivorship-free universe + `--pit-universe`) is delivered
and works; quantifying the *classic* survivorship penalty (holding a coin **as** it craters)
requires a **test window spanning the 2022 crashes**, which is [[T0007-multi-window-training-stress-harness]]
— now data-enabled by this iteration. T0005's question is answered; the crisis-window
measurement lives in T0007.
