# iter-37 — Stage-1: per-asset selection *composed* on top of the market gate (`tsmom_compose`) (design)

**Goal:** test whether per-asset trend **selection layered ON TOP of** `beta_null`'s market gate beats the
null — keeping the proven full-cash-in-BTC-bear defense and, in non-bear, holding only the coins above their
own 100d SMA. **Success bar:** positive mean delta-vs-null whose bootstrap CI clears 0. (User-directed
"take iter-37 (compose)"; decisions `.tmp/decisions.md` iter-037.)

## Context

iter-35/36 showed per-asset trend gating **replacing** the market gate is refuted at both windows (100d
whipsaws on bear bounces; 200d holds alts into the crash) — it can't replicate the market gate's clean
full-cash-in-bear. The reframe this iteration tests: **don't replace the market gate — compose with it.**
Keep `beta_null`'s BTC-200d gate (the unmatched bear defense) and use the per-asset 100d trend filter only
to *select within* the already-bear-defended basket. The 100d whipsaw that sank iter-35 cannot fire here —
in a BTC-bear the whole basket is already cashed by the market gate, so there are no coins to re-enter.

## Design — one variable vs `beta_null`

Keep `beta_null`'s book verbatim; **add** per-asset selection that composes with (does not replace) the gate.

- **Strategy:** add `compose_market_gate: bool = False` to `VolWeightedRegimeStrategy`. The market-gate
  multiplier is disabled (returns 1.0) **only when** `trend_window is not None AND NOT compose_market_gate`
  (the iter-35 "replace" mode). When `compose_market_gate=True`, the BTC-200d multiplier stays active **and**
  the per-asset trend filter (drop coins ≤ own SMA) also applies. `trend_window=None` ⇒ unchanged
  (back-compat: `beta_null`, `regime_volweight_majors`); `tsmom_voltarget`/`_w200` keep replace-mode behaviour
  (they don't set the flag).
- **`tsmom_compose` recipe:** `beta_null`'s book + `trend_window=100` + `compose_market_gate=True`. Everything
  else frozen identical, so the A/B isolates "per-asset selection on top of the gate."

## Validation

`zcrypto stress --recipe tsmom_compose --null beta_null` → per-window + across-window delta-vs-null with the
paired bootstrap CI, plus the CPCV distribution. Read cost-adjusted, not gross.

## Success / kill

- **Win:** mean delta-vs-null > 0, CI clears 0 → per-asset selection adds bull-side value on top of the
  bear-defended basket; the first Stage-1 improvement over the null. Next would tune the window / add intraday vol.
- **Null/negative:** delta ≈ 0 or CI straddles → selecting trending coins doesn't beat holding the full
  top-10 even when composed. **Combined with iter-35/36, per-asset TSMOM is then exhausted** — the
  "shelve per-asset gating, pivot Stage-1 to derivatives-positioning" call (high-stakes) is strongly
  evidenced but stays **parked for an attended session** (not ratified autonomously).

## Testing (TDD)

- **compose strategy mode** — unit (inject the membership/close seams): with `trend_window=100,
  compose_market_gate=True`, the market gate still zeroes exposure in a BTC-bear (cash) AND the per-asset
  filter drops below-SMA names in non-bear; with `compose_market_gate=False` the gate is disabled (iter-35
  replace behaviour, unchanged); `trend_window=None` byte-identical to today.
- **`tsmom_compose` drift-guard** — `beta_null`'s frozen params + `trend_window=100` + `compose_market_gate=True`.
- **stress A/B** — redis-gated: `stress --recipe tsmom_compose --null beta_null` writes the delta keys.

## Closeout

`docs/iterations-history.md` iter-37 entry with the measured delta-vs-null verdict; update `T0022`; if the
result is the kill case, restate the parked shelve/pivot recommendation for the human (don't ratify).
