---
status: open
---

# Funding right-edge via /fapi/v1/fundingRate API (intra-month tail)

## Context — what

iter-15's `$funding` is sourced from Binance's immutable **monthly** Vision archives (`futures/um/monthly/fundingRate`), which publish only after a month closes. The funding right-edge therefore trails the kline right-edge by up to ~a month — the current, unpublished month reads `NaN`. Binance's `/fapi/v1/fundingRate` REST endpoint returns the already-settled funding for the *open* month, so it can fill that tail and bring `$funding`'s right edge in line with the other features. Needed for **live prediction** (deciding today), not for historical backtesting.

## Why this matters

For live/recent inference, funding is the genuinely-new signal; if its most recent ~month is `NaN`/neutral while every other feature is current, the live signal is degraded exactly when it is used. Backtests over historical holdouts are unaffected (the monthly archives fully cover the past), so this is a **live-readiness** step, not a research blocker.

## Findings so far

Design sketch from the iter-15 follow-up discussion (PR #47):

- **Immutability mismatch.** The `raw/` mirror trusts monthly archives as immutable (cached forever, read without re-checksum). The API's current month is mutable/partial, so it cannot live in the `monthly/` tree.
- **Storage — provisional namespace.** Keep a separate `raw/futures/um/api/fundingRate/<PERP>/<PERP>-fundingRate-<YYYY-MM>.json` subtree: re-fetched while the month is open, retired once that month's monthly archive publishes. (Simpler alternative: don't persist — live-fetch the tail each run; loses offline-rebuild fidelity at the edge.)
- **Precedence — archive wins per (perp, month).** The API fills only months with no archive yet (the open tail); `_funding_for_pair` chooses the source per month.
- **Backfill, intra-month:** months ≤ last-archived → archive mirror-hits; current month → API fetch → the bin's right edge tracks the kline edge. **Backfill, next-month:** once the month's archive publishes, the archive supersedes → that month is re-filled from the immutable archive and the provisional `api/` snapshot is pruned. The historical record always converges to the archives; any intra-month API approximation is discarded once the archive lands.
- **Loose ends.** `/fapi/v1/fundingRate` is `fapi.binance.com` (weight-rate-limited, paginated `limit=1000`, public/no-auth) vs the static Vision host; add `Source.fetch_funding_api(perp, start_ms, end_ms)`; `parse_funding` gains a JSON variant feeding the same `daily_funding` aggregation; `verify`'s right-edge shrinks to the single unsettled bar.

## Suggested next steps

- Decide whether to persist the provisional API tail (offline-rebuild fidelity) or live-fetch it each run (simpler).
- Add `Source.fetch_funding_api` + a JSON `parse_funding` variant; wire archive-wins-per-month precedence into `_funding_for_pair`.
- Validate the intra-month → next-month handoff (API tail filled, then superseded by the archive with the provisional snapshot pruned).
- Sequence as a small live-readiness data iteration, after the funding *feature* / edge-test confirms funding is worth carrying to live.
