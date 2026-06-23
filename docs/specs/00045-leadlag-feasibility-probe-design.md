# iter-51 — BTC→alt intraday lead-lag: feasibility probe (`T0020`) (design)

**Goal:** decisively answer **"does a BTC(/ETH)→alt intraday lead-lag signal exist, large enough to plausibly
survive cost?"** with a cheap, fully-reversible **offline statistical probe** — BEFORE committing to the
multi-week 1h-data + intraday-harness build. **GO/NO-GO** on a pre-registered, multiple-testing-aware test.
Decisions `.tmp/decisions.md` iter-051; scoped by the `leadlag-scope` workflow. The first phase of `T0020`.

## Context

`T0020` (the orientation's top relative-alpha idea) hypothesizes slow cross-coin information diffusion: BTC/ETH's
recent intraday move predicts altcoin moves over the next 1–6h — **structurally invisible to the daily-bar work**
that hit the `T0018` OHLCV-alpha wall. It needs intraday (1h) data + an intraday backtest harness — a heavy build.
This probe is the **cheapest decisive gate**: a self-contained offline pandas/numpy study (no qlib, no harness,
no `SUPPORTED_INTERVALS` change) on a throwaway 1h pull, that measures raw predictability + economic plausibility.
**Honest ceiling:** it measures predictability + economic plausibility, NOT realized net-of-cost tradeability — a
GO *licenses the harness build* (Phases A–E below), it does not pre-validate profitability.

## Design — offline probe (fully reversible)

- **Data (throwaway, `.tmp/`):** fetch free Binance **1h spot klines** for the 10 curated majors in
  `cli/experiment/recipes/regime_equalweight_majors.py` (BTC, ETH, BNB, SOL, XRP, ADA, AVAX, LINK, DOGE, TRX) over
  **2023-01-01..2025-12-31** from `data.binance.vision/.../klines/{SYM}/1h/{SYM}-1h-{YYYY-MM-DD}.zip`. Reuse
  `cli/data/binance.py` URL builders + the concurrent fetcher, but a **probe-local 24-row parser** (the existing
  `cli/data/klines.py:parse_kline_zip` hard-asserts a single daily row and drops the hour) that keeps the full UTC
  hour timestamp, with per-row ms/µs unit auto-detection (mirror `_open_time_to_date`). Land a tidy frame
  (`timestamp_open_utc, symbol, open, high, low, close, volume`) in `.tmp/` (gitignored). ~11k zips, a few MB, ~2 min
  over 8 threads. **Predictors:** BTC, ETH. **Targets:** the other 8 alts (never self-predict). Do NOT touch the
  pipeline/qlib writer or `SUPPORTED_INTERVALS`.
- **Pre-registration (before any data is read):** write the full grid `(predictor∈{BTC,ETH}) × (k∈{1,2,3,6}h) ×
  (h∈{1,2,3,4,6}h)` and the resulting `N_trials` to disk; the verdict cites `N_trials` and leads with the ~40 pooled
  cells, not the hundreds of per-coin t-stats.
- **Method — pooled predictive regression** per cell: `r_alt,i(t→t+h) = α_i + β·r_pred(t−k→t) + γ·r_alt,i(t−k→t) + ε`
  (alt fixed effects via per-alt demeaning; the `γ` own-lag term controls the alt's own short-horizon
  autocorrelation so it isn't mislabeled as a BTC lead). **Verdict leads with the pooled `β`** (the hypothesis is a
  BTC→basket time-series lead); cross-sectional **rank-IC** is the secondary, strategy-facing read; lagged
  cross-correlation is a pre-screen heatmap only.
- **LOOK-AHEAD (the #1 false-positive source):** a 1h bar stamped 12:00 closes at 13:00, so the predictor
  `t−k→t` return is known only at that close and the forward window `t→t+h` must start at the same close — enforce a
  one-bar buffer + an explicit **assertion** `predictor_window.close_time ≤ forward_window.start_time` (an assert,
  not a comment).
- **False-positive controls:** (1) pre-registered grid + `N_trials`; (2) Newey-West HAC SEs (lag=h−1) for the
  overlapping forward windows; (3) timestamp-clustered SEs (all 8 alts at hour t share the BTC shock); (4) BH-FDR
  q-values across the grid + a **deflated-for-N_trials IC haircut** (the IC analogue of
  `stats.expected_max_sharpe`/`deflated_sharpe`) + a **stationary-bootstrap 95% CI** on the rank-IC (reuse
  `cli/experiment/stats.py:stationary_bootstrap_ci`, block ≥ h); (5) **per-year split (2023/24/25)** requiring same
  sign all three years, a non-overlapping cross-check (sample every h hours), and a rolling-60-day IC plot.
- **False-negative avoidance:** 1h primary resolution (daily bars alias the whole signal); the full h-grid + report
  the **decay profile** (a real diffusion effect rises then decays; a single-lag spike is a noise red flag); one
  **confirmatory 15m spot-check** (not a full 15m grid).
- **Economic relevance (the binding bar):** convert the headline cell to a **top-vs-bottom-decile forward-alt-return
  spread (bps)** by BTC-impulse decile, vs the calibrated **~4.4 bps round-trip** from `cli/experiment/costs.py`;
  report `net_edge ≈ gross_decile_spread − roundtrip_cost` (net, honoring the gross-vs-net lesson).

## Success / kill (GO requires ALL four)

1. **Statistical:** headline pooled IC/β survives BH-FDR (q<0.05) AND stays positive after the deflated-N_trials
   haircut AND its bootstrap 95% CI excludes 0.
2. **Regime-stable:** same sign across 2023/24/25, non-trivial in the two most recent years (a sign-flip is a hard
   refutation regardless of the full-sample number — the `T0018` scar).
3. **Economic:** the decile spread exceeds **~3× the 4.4 bps round-trip (~13–15 bps gross)**; secondary rank-IC
   ≳ 0.03–0.05 at the best `(k,h)`.
4. **Coherent decay:** IC rises over ~1–3h then decays (implying a multi-hour hold) — a signal alive only at h=1
   must trade hourly and cost almost certainly dominates.

Read the verdict on the **deflated / lower-CI** number net of cost, **never the peak**. **GO** → build Phases A–E.
**Any one fails → NO-GO**: document, keep only as a possible minor overlay per `T0020`'s kill clause, do NOT build.

## Outputs

Pre-registration file; headline table (β + rank-IC per cell with HAC+clustered t-stat, BH-FDR q, bootstrap CI,
deflated-IC); per-year table (+ same-sign flag); per-alt breakdown for the best cell (concentration check); economic
decile-spread table (+ net_edge); non-overlapping cross-check; plots (IC-decay, k×h heatmap, rolling-60d IC,
cross-correlation pre-screen); 4h-aggregation + 15m-spot-check robustness reruns; the four-condition GO/NO-GO verdict.

## Testing (TDD — correctness is load-bearing)

- **Known-signal recovery:** a synthetic 1h panel with an INJECTED BTC→alt lead at a known (k,h) → the probe
  recovers it (right cell, right sign, significant).
- **Known-null rejection:** a synthetic panel with NO lead (independent / only own-autocorrelation) → the probe
  reports null after BH-FDR + deflation (does NOT false-positive); the `γ` own-lag control absorbs pure alt
  autocorrelation.
- **Look-ahead assertion fires:** a deliberately misaligned predictor/forward window trips the assertion.
- **Parser unit:** synthetic 1h zip → 24 rows/day, correct hour timestamps, ms/µs auto-detect.
- Keep the data fetch out of unit tests (synthetic frames / monkeypatch).

## Where it lives

A committed, tested probe module (e.g. `cli/research/leadlag_probe.py` + tests) — reusable + the reviewable trail;
the 1h data + result artifacts go to `.tmp/` (gitignored). Run via `uv run python -m ...`.

## Closeout

`docs/iterations-history.md` iter-51 entry with the GO/NO-GO verdict (read on the deflated/CI-lower number net of
cost, citing N_trials); update `T0020` (→ partial: probe done, verdict, phased plan A–E recorded). If GO, the next
iteration is Phase A (1h data infrastructure); if NO-GO, the lead-lag thread is refuted/parked and the loop picks
the next thread.
