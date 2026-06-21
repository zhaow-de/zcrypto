---
status: open
---

# Force-liquidate-to-cash on mid-backtest delisting

## Context — what

When a held pair's data ends mid-backtest (a delisting), qlib **freezes** the position
at its last marked value rather than liquidating it to cash. A recon during iter-18
(forcing a portfolio to hold `NANOUSDT` through its 2022-01-24 delisting) confirmed this:
the mark-to-market loss while the coin still had data flows into the portfolio (the
survivorship loss *is* captured), but after the last bar the position is held flat — the
capital is **trapped**, not redeployed into live names.

## Why this matters

The freeze is *conservative for the loss* (the drawdown to the last close is realized) but
*optimistic-blocking for the recovery* — trapped capital sits idle instead of rotating into
tradeable instruments, understating the achievable return after a delisting. This does not
bite the iter-18 re-measure (its 2025+ holdout postdates every acquired blow-up, so no coin
delists mid-test), but it **will** bite a crisis-spanning test where a held coin craters and
delists inside the window — i.e. the survivorship stress that `T0007` (multi-window /
crisis-stress harness) will run on the now-acquired blow-up data. See [[T0007-multi-window-training-stress-harness]]
and [[T0005-point-in-time-universe]].

## Findings so far

- iter-18 delisting-freeze recon: qlib's `SimulatorExecutor` does not error or silently drop
  a delisted holding — it freezes the position at the last close (loss captured, capital not
  redeployed).
- Not exercised by the iter-18 re-measure (no mid-test delistings in the 2025+ window).

## Suggested next steps

- Model a **force-liquidate-to-cash at the last available close** when a held pair's data
  ends (a strategy- or exchange-layer hook), so freed capital can rotate into live names.
- Re-measure under a 2022-spanning `T0007` crisis window (where coins delist mid-test) to
  quantify how much the freeze-vs-liquidate choice moves the result.
