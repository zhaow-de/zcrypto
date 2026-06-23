# iter-53 — Anti-whipsaw confirmation filter on the regime gate (`beta_null_confirm5`) (design)

**Goal:** test whether a **confirmation/debounce filter** on `beta_null`'s BTC-200d gate — require N consecutive
days on the new side before the gate flips — improves the passive-beta yardstick by cutting whipsaw around the
200d crossing. **Success bar:** mean delta-vs-`beta_null` > 0 with bootstrap CI clearing 0 (a real refinement of
the *winner*). Decisions `.tmp/decisions.md` iter-053; the untested anti-whipsaw lever of `T0017`.

## Context

The substantive alpha threads are explored (momentum POSITIVE-but-parked for the holdout; derivatives tapped;
on-chain refuted/parked; lead-lag `T0020` refuted; per-asset TSMOM exhausted; OHLCV-ML exhausted). The most
defensible reversible thread left is **refining the winner** (`beta_null`, the passive-beta null). `T0017`'s
anti-whipsaw confirmation filter is a defined, UNTESTED lever: `beta_null`'s binary gate (`close_BTC > SMA200`)
flips the instant BTC crosses its 200d MA, so a choppy crossing whipsaws the gate (on/off/on) — each false flip
costs (a brief de-risk then re-enter, or vice versa). A confirmation filter debounces this.

## Design — one knob vs `beta_null`

- **`regime_exposure_series` (the shared gate fn):** add `confirm_days: int = 0`. When `confirm_days > 0`,
  debounce the **binary** gate signal: the held gate state flips to the opposite side only after the raw signal
  (`close > sma`) has been on that opposite side for **N consecutive days** (a causal Schmitt-trigger/debounce).
  Implementation: after computing the raw 0/1 `mult` (before the vol-target scale), run a causal pass that
  tracks the held state + a consecutive-opposite-day counter, flipping only when the counter reaches N. The
  held state at day t depends ONLY on raw values ≤ t (no look-ahead). Warmup (SMA NaN) stays fully invested as
  today, and seeds the initial held state. `confirm_days=0` ⇒ byte-identical to today. (Apply the debounce to
  the binary path; `beta_null` is binary. The vol-target scale, if any, multiplies the debounced gate as before.)
- **`VolWeightedRegimeStrategy`:** add `regime_confirm_days: int = 0`, threaded into the
  `regime_exposure_series(...)` call in `_build_exposure`. `getattr` guard; default 0 = unchanged.
- **`beta_null_confirm5` recipe:** `beta_null`'s book + `regime_confirm_days=5`. Everything else frozen.

## Validation

`zcrypto stress --recipe beta_null_confirm5 --null beta_null` → per-window + across-window delta-vs-null +
bootstrap CI + CPCV. Read cost-adjusted.

## Success / kill

- **Win:** mean delta > 0, CI clears 0 → the confirmation filter cuts harmful whipsaw and refines the gate;
  next sweep N (3/5/10) to find the cost-optimal debounce and consider applying it to other gated recipes.
- **Null/negative:** the confirmation lag costs more than the whipsaw it prevents (consistent with the iter-35/36
  finding that the gate's clean full-cash-in-bear is already its virtue) → the `T0017` anti-whipsaw lever is
  **closed**; `beta_null`'s instant binary gate stands.

## Testing (TDD)

- **debounce unit** (`regime_exposure_series` with `confirm_days=5` on a synthetic close/SMA): a brief 2-day
  crossing does NOT flip the confirmed gate; a sustained 5-consecutive-day crossing DOES flip it (on day 5).
- **no look-ahead:** the confirmed state at day t is unchanged by appending future rows (truncation-invariant).
- **back-compat:** `confirm_days=0` ⇒ the gate series is byte-identical to today (binary/graded/cross all
  unaffected when 0); `regime_confirm_days=0` on the strategy ⇒ unchanged exposure.
- **`beta_null_confirm5` drift-guard:** `beta_null` + exactly the `regime_confirm_days` kwarg.
- **stress A/B** — redis-gated.

## Closeout

`docs/iterations-history.md` iter-53 entry with the delta-vs-`beta_null` verdict; update `T0017` (anti-whipsaw
lever: win → sweep N, or closed). If win, `beta_null_confirm5` (or the swept-N best) is a refined baseline.
