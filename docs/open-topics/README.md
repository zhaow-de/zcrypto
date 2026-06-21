# Open topics

Topics worth follow-up are parked here, one file per topic. See `.claude/rules/open-topics.md` for the convention.

<!-- mdformat-toc start --slug=github --maxlevel=3 --minlevel=2 -->

- [Research and development](#research-and-development)
  - [Open](#open)
  - [Partially done](#partially-done)
  - [Resolved](#resolved)
- [Live trading preparation](#live-trading-preparation)
  - [Open](#open-1)
  - [Partially done](#partially-done-1)
  - [Resolved](#resolved-1)

<!-- mdformat-toc end -->

## Research and development<a name="research-and-development"></a>

### Open<a name="open"></a>

- [T0000 — qlib empty-slice warnings](T0000-qlib-empty-slice-warnings.md) — benign `RuntimeWarning: Mean of empty slice` from `qlib/utils/index_data.py`; suppressed in `cli/logging/config.py`, remove when qlib upstream guards the empty-slice case.
- [T0001 — pandas concat-with-empty FutureWarning](T0001-pandas-concat-empty-futurewarning.md) — \_build_staging concats an empty new_df for no-new-row pairs; benign today (write_bin force-casts) but pandas will change empty-frame dtype inference; guard the concat.
- [T0009 — Walk-forward position carry-over](T0009-walkforward-position-carryover.md) — iter-12 walk-forward starts each retrain period all-cash, incurring artificial re-entry costs at boundaries; carry positions across period boundaries to remove the seam.
- [T0014 — Force-liquidate-to-cash on mid-backtest delisting](T0014-force-liquidate-on-delisting.md) — qlib freezes a held position at its last close when a coin delists (loss captured, capital not redeployed); model a liquidate-to-cash so freed capital rotates into live names.
- [T0015 — Holdout `ending_value` is gross (pre-cost)](T0015-holdout-ending-value-gross.md) — the `--seeds` holdout reports `ending_value` from the gross return while its Sharpe/PSR are cost-adjusted, so the headline account value overstates net P&L and is cost-insensitive (surfaced by the iter-19 cost A/B); make it cost-adjusted + audit the single-run path.
- [T0017 — Regime-overlay tuning](T0017-regime-overlay-tuning.md) — the slow binary-200d gate Pareto-beats `steady` OOS (mean Sharpe 0.289 vs 0.154, iter-23) and vol-targeting is a slim win (`regime_voltarget` 0.311, iter-24); all feature-stacking levers (graded, funding, cross-asset) are closed and `regime_voltarget` is the ~0.31 OOS defensive ceiling. Narrowed to two remainders: an un-tested anti-whipsaw filter (low EV) and retiring the now-submitted qlib `get_risk_degree` workaround once it ships upstream.
- [T0018 — OOS signal-generalization wall](T0018-oos-signal-generalization-wall.md) — the daily-OHLCV cross-sectional alpha (CPCV ~+1.0) inverts OOS on 2025+; feature axis (iter-25/26) AND model axis (iter-27, linear≈LGBM) both ruled out — the failure is the signal, not features/model. Next frontier: new information (on-chain, T0010) or accept the `regime_voltarget` ~0.31 defensive ceiling.
- [T0019 — Time-series trend-following + vol-targeting core (and the passive-beta null)](T0019-tsmom-voltarget-core.md) — the highest-EV Phase-2 candidate: per-asset time-series momentum + volatility-targeting (long/cash on spot) as the prospective new *core*, plus the Stage-0 passive-beta null (200d-SMA-gated inverse-vol majors) that every later idea must beat net of costs. Spawned by `docs/research/03.phase2-orientation.md`.
- [T0020 — BTC→altcoin lead-lag (intraday cross-coin predictability)](T0020-btc-alt-lead-lag.md) — the top genuine relative-alpha (Channel B) idea: whether BTC/ETH's recent intraday move predicts altcoin moves over the next hours (slow cross-coin information diffusion), tested at 1h granularity — structurally invisible to the daily-bar work that hit the T0018 wall.
- [T0021 — On-chain regime overlay vs the 200d-SMA gate](T0021-onchain-regime-vs-sma.md) — demotes on-chain (T0010) from "the frontier" to one timing contender: the falsifiable head-to-head of BTC/ETH on-chain regime signals (MVRV-Z, NUPL, flows) vs the 200d-SMA gate, net of costs — adopt only if it beats SMA OOS.

### Partially done<a name="partially-done"></a>

- [T0010 — Non-OHLCV features (funding-rate / on-chain / order-book)](T0010-non-ohlcv-features.md) — the **funding** stream landed in iter-15; on-chain + order-book remain — now the **prime R&D frontier** (per T0018: OHLCV-derived alpha is exhausted, so genuinely new information is the only untried lever for an OOS-surviving edge).

### Resolved<a name="resolved"></a>

- [T0002 — Validation rigor (purged CV, CPCV, deflated Sharpe)](archive/T0002-validation-rigor.md) — purged k-fold + embargo + CPCV (iter-9), then per-recipe PSR + the `rank` command's deflated Sharpe + PBO (iter-11) — validation rigor resolved.
- [T0003 — BTC-trend regime overlay (long/cash gating)](archive/T0003-btc-regime-overlay.md) — `RegimeGatedTopkStrategy` with binary/graded/cross modes + vol-targeting knob shipped in iter-12 (spec `00011`); demo recipe `regime_steady`; exposure via `get_risk_degree`.
- [T0011 — Nondeterministic experiment results / multi-seed validation](archive/T0011-nondeterministic-results-multi-seed.md) — iter-14 shipped `--seeds N` / `--deterministic`; 16-seed re-run confirmed single-run verdicts were seed-noise; true order inverts iter-13's ranking; single-run holdout verdicts retired in favour of distributions.
- [T0005 — Point-in-time universe / survivorship](archive/T0005-point-in-time-universe.md) — iter-16 acquired the survivorship-free data substrate; iter-18 added the `--pit-universe` lever + the Terra LUNCUSDT blow-up (capped before Luna 2.0) and re-measured all recipes survivor-vs-PIT: **no inflation** (PIT equal-or-better) because the 2025+ holdout postdates the 2022/2024 collapses — the classic crash-window penalty is handed to T0007.
- [T0004 — Realistic execution (slippage + maker-fill)](archive/T0004-execution-slippage-fills.md) — iter-17 landed the aggTrades data; iter-19 made calibrated realistic costs the default (qlib `impact_cost` + a maker-fill haircut, calibrated from the sample) with a `--fees-only` baseline. Verdict: a small consistent drag (paired Sharpe −0.012) — slippage negligible at $10k, the ~2.2 bps maker-fill haircut dominates, scaling with turnover.
- [T0007 — Multi-window training-stress harness](archive/T0007-multi-window-training-stress-harness.md) — the OOS test-window walk-forward (`zcrypto stress`) shipped (iter-22) and proved the OOS-generalization wall (T0018); the training-window axis is infeasible (no pre-2020 data) and further multi-window sweeping is moot now that the OHLCV/regime vein is exhausted.
- [T0008 — Pluggable feature handler](archive/T0008-pluggable-feature-handler.md) — the `feature_config` seam shipped + was exercised (iter-13); the remaining feature axes are OHLCV-derived (closed by T0018), and the only live feature frontier — non-OHLCV data — lives in T0010.
- [T0012 — Prediction-ensemble (seed-averaged signal)](archive/T0012-prediction-ensemble.md) — a stability lever for a *selected* ML signal, but ML cross-sectional selection is net-harmful OOS (iter-29) and the deployable is no-ML, so there is no signal to ensemble.
- [T0016 — First-class market-neutral long/short strategy / recipe](archive/T0016-market-neutral-ls-strategy.md) — hard-gated on an L/S edge surviving OOS; that gate failed (iter-22, steady L/S mean −0.10) and the OHLCV alpha axis is exhausted, so there is nothing to promote — reopen only if T0010 yields an OOS-surviving L/S edge.

## Live trading preparation<a name="live-trading-preparation"></a>

### Open<a name="open-1"></a>

- [T0006 — Paper-trading harness before live](T0006-paper-trading-harness.md) — the skeleton ends at backtest; before live, add ≥3-month paper trading vs live Binance with a backtest-divergence gate (Stage 4).

### Partially done<a name="partially-done-1"></a>

_(none)_

### Resolved<a name="resolved-1"></a>

- [T0013 — Funding right-edge via /fapi/v1/fundingRate API](archive/T0013-funding-right-edge-api.md) — moot: the funding feature did not survive the OOS edge-test (a defensive low-beta tilt, redundant with regime timing), so it is not carried to the live signal — no live funding signal means no consumer for the intra-month right-edge fix.
