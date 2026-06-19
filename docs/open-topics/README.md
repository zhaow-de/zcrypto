# Open topics

Topics worth follow-up are parked here, one file per topic. See `.claude/rules/open-topics.md` for the convention.

<!-- mdformat-toc start --slug=github --maxlevel=2 --minlevel=2 -->

- [Open](#open)
- [Partially done](#partially-done)
- [Resolved](#resolved)

<!-- mdformat-toc end -->

## Open<a name="open"></a>

- [T0000 — qlib empty-slice warnings](T0000-qlib-empty-slice-warnings.md) — benign `RuntimeWarning: Mean of empty slice` from `qlib/utils/index_data.py`; suppressed in `cli/logging/config.py`, remove when qlib upstream guards the empty-slice case.
- [T0001 — pandas concat-with-empty FutureWarning](T0001-pandas-concat-empty-futurewarning.md) — \_build_staging concats an empty new_df for no-new-row pairs; benign today (write_bin force-casts) but pandas will change empty-frame dtype inference; guard the concat.
- [T0004 — Realistic execution (slippage + maker-fill)](T0004-execution-slippage-fills.md) — **[Medium]** fees are modeled but fills are frictionless; add size-scaled slippage + maker-fill probability from an aggTrades sample before trusting net P&L.
- [T0005 — Point-in-time universe / survivorship](T0005-point-in-time-universe.md) — **[Medium]** the skeleton trades today's 19-pair universe across all history; build point-in-time membership + delisting handling to avoid survivorship-inflated results.
- [T0006 — Paper-trading harness before live](T0006-paper-trading-harness.md) — **[Low]** the skeleton ends at backtest; before live, add ≥3-month paper trading vs live Binance with a backtest-divergence gate (Stage 4).
- [T0007 — Multi-window training-stress harness](T0007-multi-window-training-stress-harness.md) — **[Medium]** no harness re-runs a recipe across training-window choices (2017 vs 2020 start) and through LUNA/FTX; needed for §13 Stage 3 robustness aggregation.
- [T0009 — Walk-forward position carry-over](T0009-walkforward-position-carryover.md) — **[Low]** iter-12 walk-forward starts each retrain period all-cash, incurring artificial re-entry costs at boundaries; carry positions across period boundaries to remove the seam.
- [T0012 — Prediction-ensemble (seed-averaged signal)](T0012-prediction-ensemble.md) — **[Medium]** averaging N seed-trained models into one signal *reduces* run-to-run variance (and may lift the signal), vs iter-14's multi-seed distribution which only *measures* it; a small additive step on the multi-seed machinery, a candidate production-stability lever once a recipe is selected.

## Partially done<a name="partially-done"></a>

- [T0008 — Pluggable feature handler](T0008-pluggable-feature-handler.md) — **[Medium]** `feature_config` seam + Alpha360 + custom cross-asset handler shipped in iter-13; non-OHLCV features (funding/on-chain) remain open in T0010.
- [T0010 — Non-OHLCV features (funding-rate / on-chain / order-book)](T0010-non-ohlcv-features.md) — **[Medium]** the **funding** stream landed in iter-15 (`$funding` qlib field woven into all `zcrypto data` subcommands + an idempotent retrofit); the funding *feature*/recipe/edge-test, plus on-chain and order-book streams, remain.

## Resolved<a name="resolved"></a>

- [T0002 — Validation rigor (purged CV, CPCV, deflated Sharpe)](T0002-validation-rigor.md) — purged k-fold + embargo + CPCV (iter-9), then per-recipe PSR + the `rank` command's deflated Sharpe + PBO (iter-11) — validation rigor resolved.
- [T0003 — BTC-trend regime overlay (long/cash gating)](T0003-btc-regime-overlay.md) — `RegimeGatedTopkStrategy` with binary/graded/cross modes + vol-targeting knob shipped in iter-12 (spec `00011`); demo recipe `regime_steady`; exposure via `get_risk_degree`.
- [T0011 — Nondeterministic experiment results / multi-seed validation](T0011-nondeterministic-results-multi-seed.md) — iter-14 shipped `--seeds N` / `--deterministic`; 16-seed re-run confirmed single-run verdicts were seed-noise; true order inverts iter-13's ranking; single-run holdout verdicts retired in favour of distributions.
