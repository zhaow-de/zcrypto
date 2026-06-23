# iter-46 — Stage-2: keyless on-chain NVM regime overlay (`onchain_regime`) (design)

**Goal:** test a **genuinely different alpha source** — a BTC on-chain valuation regime — as a market-timing
de-risk overlay on `beta_null`. **Success bar:** mean delta-vs-`beta_null` > 0 with bootstrap CI clearing 0.
Decisions `.tmp/decisions.md` iter-046; `T0021`.

## Context — and a data-availability discovery

`T0021` and the orientation assumed keyless Coin Metrics MVRV-Z/NUPL. **It doesn't have them:** the community
(keyless) API returns `forbidden` for `CapRealUSD` (realized cap → MVRV) and `TxTfrValAdjUSD` (transfer value
→ NVT) — those need a **credentialed** plan (PARKED, the credentialed-data item). Keyless BTC metrics that ARE
available: `CapMrktCurUSD` (market cap), `AdrActCnt` (active addresses), `TxCnt`, `HashRate`, `SplyCur`.

So this iteration uses the best **keyless** on-chain valuation proxy: **NVM** (Network-Value-to-Metcalfe).
Metcalfe's law says network value ∝ users² ; using active addresses as users, `NVM = log(CapMrktCurUSD /
AdrActCnt²)`. When NVM is extreme-**high** (vs its own trailing history), price has outrun on-chain usage —
**overvalued** — a cycle-top signal the 200d-SMA gate may lag. The overlay de-risks then.

## Design — a de-risk overlay vs `beta_null` (mirrors the iter-39 froth overlay)

- **Fetcher (`cli/data/onchain.py`):** a keyless Coin Metrics fetcher `fetch_btc_onchain()` → paginated GET on
  `https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=CapMrktCurUSD,AdrActCnt&frequency=1d`
  over the full history → a date-indexed DataFrame (`market_cap`, `active_addr`). A `build_btc_nvm_cache(path)`
  computes `nvm = log(market_cap / active_addr**2)` and writes a date-indexed parquet (default
  `data/onchain/btc_nvm.parquet`, gitignored). Uses the repo's existing `urllib3`/retry patterns; the network
  fetch is **not** exercised in unit tests (inject/monkeypatch). This is a one-time cache build the loop runs
  before the A/B — NO new CLI subcommand (call via `python -c`), so no README change.
- **Strategy (`VolWeightedRegimeStrategy`):** add `onchain_regime: bool = False` (off → back-compatible),
  `onchain_path: str | None`, `onchain_z_window: int = 365`, `onchain_z_threshold: float = 1.0`,
  `onchain_derisk_mult: float = 0.0`. A lazy `_build_onchain_signal()` reads the parquet → `nvm` series →
  trailing z-score `(nvm − nvm.rolling(z_window).mean()) / nvm.rolling(z_window).std()` (causal). In
  `_mult_for(date)` (where the exposure multiplier is built), if `onchain_regime`: look up the
  **strictly-prior** NVM-z (carry-forward ≤ t, same discipline as `_exposure`); if `nvm_z >
  onchain_z_threshold` (overvalued), multiply the exposure multiplier by `onchain_derisk_mult` (0.0 = cash).
  NaN/warmup → no de-risk (mult 1.0). Injectable `_onchain_signal` seam. `onchain_regime=False` ⇒ byte-identical.
  No look-ahead: rolling z + strictly-prior lookup. (This mirrors the iter-39 froth overlay, with NVM-z as the
  signal source read from the cache instead of a `$field`.)
- **`onchain_regime` recipe:** `beta_null`'s book + `onchain_regime=True`, `onchain_path` to the cache,
  `onchain_z_threshold=1.0`, `onchain_derisk_mult=0.0`. Frozen otherwise.

## Validation

Build the cache (`build_btc_nvm_cache`), then `zcrypto stress --recipe onchain_regime --null beta_null` →
per-window + across-window delta-vs-`beta_null` + bootstrap CI + CPCV. Read cost-adjusted.

## Success / kill

- **Win:** mean delta > 0, CI clears 0 → the on-chain valuation regime adds timing value over the SMA gate;
  next tune the threshold / try a graded de-risk / a head-to-head gate-replacement.
- **Null/negative:** NVM (the keyless proxy) adds no timing edge. Record it; the **credentialed** MVRV-Z/NUPL
  thread (the stronger valuation metric) is **parked** for an attended session — note that the keyless proxy
  failing does NOT condemn MVRV-Z (a better metric), so the parked credentialed thread stays open.

## Testing (TDD)

- **NVM signal unit:** `build_btc_nvm_cache` / the NVM computation on a synthetic market-cap+addresses frame →
  `nvm = log(mcap/addr²)`; the trailing z is causal (truncation-invariant); NaN in warmup.
- **overlay unit** (inject `_onchain_signal` + `_exposure`): on a date where prior NVM-z > threshold → exposure
  multiplier is scaled by `onchain_derisk_mult` (cash at 0.0); where NVM-z ≤ threshold (or NaN) → no de-risk;
  no look-ahead (strictly-prior).
- **fetcher unit:** monkeypatch the HTTP layer → assert pagination + the metric parsing + NaN handling; NO real network.
- **`onchain_regime` drift-guard:** `beta_null` + exactly the on-chain kwargs.
- **back-compat:** `onchain_regime=False` byte-identical; the froth/tilt overlays untouched.
- **stress A/B** — redis-gated.

## Closeout

`docs/iterations-history.md` iter-46 entry with the delta-vs-`beta_null` verdict + the data-availability
discovery; update `T0021` (keyless = NVM only; MVRV-Z/NUPL need credentialed → parked).
