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
- [T0009 — Walk-forward position carry-over](T0009-walkforward-position-carryover.md) — **[Low]** iter-12 walk-forward starts each retrain period all-cash, incurring artificial re-entry costs at boundaries; carry positions across period boundaries to remove the seam.
- [T0012 — Prediction-ensemble (seed-averaged signal)](T0012-prediction-ensemble.md) — **[Medium]** averaging N seed-trained models into one signal *reduces* run-to-run variance (and may lift the signal), vs iter-14's multi-seed distribution which only *measures* it; a small additive step on the multi-seed machinery, a candidate production-stability lever once a recipe is selected.
- [T0014 — Force-liquidate-to-cash on mid-backtest delisting](T0014-force-liquidate-on-delisting.md) — **[Low]** qlib freezes a held position at its last close when a coin delists (loss captured, capital not redeployed); model a liquidate-to-cash so freed capital rotates into live names — matters for T0007's crisis-window survivorship stress.
- [T0015 — Holdout `ending_value` is gross (pre-cost)](T0015-holdout-ending-value-gross.md) — **[Medium]** the `--seeds` holdout reports `ending_value` from the gross return while its Sharpe/PSR are cost-adjusted, so the headline account value overstates net P&L and is cost-insensitive (surfaced by the iter-19 cost A/B); make it cost-adjusted + audit the single-run path.
- [T0016 — First-class market-neutral long/short strategy / recipe](T0016-market-neutral-ls-strategy.md) — **[Medium]** promote the market-neutral L/S to a tradeable `*_ls` strategy/recipe (resolving qlib's no-shorting) — but **gate FAILED**: iter-22 OOS validation refuted the iter-21 edge (steady L/S mean −0.10 across OOS windows), so do NOT build until a signal whose L/S edge survives OOS exists.
- [T0017 — Regime-overlay tuning](T0017-regime-overlay-tuning.md) — **[Medium]** iter-23 found the regime gate had been inert since iter-12 (a qlib `get_risk_degree` bug); once fixed, the slow binary-200d gate Pareto-beats `steady` OOS (mean Sharpe 0.289 vs 0.154) while faster gates whipsaw — vol-target a slim win (`regime_voltarget` 0.311, iter-24), graded + funding + cross-asset stacks all redundant (iter-24/25/26).
- [T0018 — OOS signal-generalization wall](T0018-oos-signal-generalization-wall.md) — **[High]** the daily-OHLCV cross-sectional alpha (CPCV ~+1.0) inverts OOS on 2025+; feature axis (iter-25/26) AND model axis (iter-27, linear≈LGBM) both ruled out — the failure is the signal, not features/model. Next frontier: new information (on-chain, T0010) or accept the `regime_voltarget` ~0.31 defensive ceiling.

### Partially done<a name="partially-done"></a>

- [T0008 — Pluggable feature handler](T0008-pluggable-feature-handler.md) — **[Medium]** `feature_config` seam + Alpha360 + custom cross-asset handler shipped in iter-13; non-OHLCV features (funding/on-chain) remain open in T0010.
- [T0010 — Non-OHLCV features (funding-rate / on-chain / order-book)](T0010-non-ohlcv-features.md) — **[High]** the **funding** stream landed in iter-15; on-chain + order-book remain — now the **prime R&D frontier** (per T0018: OHLCV-derived alpha is exhausted, so genuinely new information is the only untried lever for an OOS-surviving edge).
- [T0007 — Multi-window training-stress harness](T0007-multi-window-training-stress-harness.md) — **[Medium]** iter-22 shipped the OOS test-window walk-forward (`zcrypto stress`) — which refuted the iter-21 L/S edge OOS; the training-window axis (vary train start) stays parked (no pre-2020 data).

### Resolved<a name="resolved"></a>

- [T0002 — Validation rigor (purged CV, CPCV, deflated Sharpe)](archive/T0002-validation-rigor.md) — purged k-fold + embargo + CPCV (iter-9), then per-recipe PSR + the `rank` command's deflated Sharpe + PBO (iter-11) — validation rigor resolved.
- [T0003 — BTC-trend regime overlay (long/cash gating)](archive/T0003-btc-regime-overlay.md) — `RegimeGatedTopkStrategy` with binary/graded/cross modes + vol-targeting knob shipped in iter-12 (spec `00011`); demo recipe `regime_steady`; exposure via `get_risk_degree`.
- [T0011 — Nondeterministic experiment results / multi-seed validation](archive/T0011-nondeterministic-results-multi-seed.md) — iter-14 shipped `--seeds N` / `--deterministic`; 16-seed re-run confirmed single-run verdicts were seed-noise; true order inverts iter-13's ranking; single-run holdout verdicts retired in favour of distributions.
- [T0005 — Point-in-time universe / survivorship](archive/T0005-point-in-time-universe.md) — iter-16 acquired the survivorship-free data substrate; iter-18 added the `--pit-universe` lever + the Terra LUNCUSDT blow-up (capped before Luna 2.0) and re-measured all recipes survivor-vs-PIT: **no inflation** (PIT equal-or-better) because the 2025+ holdout postdates the 2022/2024 collapses — the classic crash-window penalty is handed to T0007.
- [T0004 — Realistic execution (slippage + maker-fill)](archive/T0004-execution-slippage-fills.md) — iter-17 landed the aggTrades data; iter-19 made calibrated realistic costs the default (qlib `impact_cost` + a maker-fill haircut, calibrated from the sample) with a `--fees-only` baseline. Verdict: a small consistent drag (paired Sharpe −0.012) — slippage negligible at $10k, the ~2.2 bps maker-fill haircut dominates, scaling with turnover.

## Live trading preparation<a name="live-trading-preparation"></a>

### Open<a name="open-1"></a>

- [T0006 — Paper-trading harness before live](T0006-paper-trading-harness.md) — **[Low]** the skeleton ends at backtest; before live, add ≥3-month paper trading vs live Binance with a backtest-divergence gate (Stage 4).
- [T0013 — Funding right-edge via /fapi/v1/fundingRate API (intra-month tail)](T0013-funding-right-edge-api.md) — the monthly-archive funding lags the kline right-edge by ~a month; fill the open-month tail via the REST funding endpoint (provisional `api/` mirror, archive-wins-per-month precedence) for live-readiness — not needed for historical backtests.

### Partially done<a name="partially-done-1"></a>

_(none)_

### Resolved<a name="resolved-1"></a>

_(none)_
