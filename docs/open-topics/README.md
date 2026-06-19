# Open topics

Topics worth follow-up are parked here, one file per topic. See `.claude/rules/open-topics.md` for the convention.

<!-- mdformat-toc start --slug=github --maxlevel=2 --minlevel=2 -->

- [Open](#open)
- [Partially done](#partially-done)
- [Resolved](#resolved)

<!-- mdformat-toc end -->

## Open<a name="open"></a>

- [00000 — qlib empty-slice warnings](00000-qlib-empty-slice-warnings.md) — benign `RuntimeWarning: Mean of empty slice` from `qlib/utils/index_data.py`; suppressed in `cli/logging/config.py`, remove when qlib upstream guards the empty-slice case.
- [00001 — pandas concat-with-empty FutureWarning](00001-pandas-concat-empty-futurewarning.md) — \_build_staging concats an empty new_df for no-new-row pairs; benign today (write_bin force-casts) but pandas will change empty-frame dtype inference; guard the concat.
- [00004 — Realistic execution (slippage + maker-fill)](00004-execution-slippage-fills.md) — **[Medium]** fees are modeled but fills are frictionless; add size-scaled slippage + maker-fill probability from an aggTrades sample before trusting net P&L.
- [00005 — Point-in-time universe / survivorship](00005-point-in-time-universe.md) — **[Medium]** the skeleton trades today's 19-pair universe across all history; build point-in-time membership + delisting handling to avoid survivorship-inflated results.
- [00006 — Paper-trading harness before live](00006-paper-trading-harness.md) — **[Low]** the skeleton ends at backtest; before live, add ≥3-month paper trading vs live Binance with a backtest-divergence gate (Stage 4).
- [00007 — Multi-window training-stress harness](00007-multi-window-training-stress-harness.md) — **[Medium]** no harness re-runs a recipe across training-window choices (2017 vs 2020 start) and through LUNA/FTX; needed for §13 Stage 3 robustness aggregation.
- [00008 — Pluggable feature handler](00008-pluggable-feature-handler.md) — **[Medium]** scaffold hardcodes `Alpha158`; make the feature handler recipe-selectable (Alpha360, custom crypto features) the way `strategy_config` made the strategy pluggable.
- [00009 — Walk-forward position carry-over](00009-walkforward-position-carryover.md) — **[Low]** iter-12 walk-forward starts each retrain period all-cash, incurring artificial re-entry costs at boundaries; carry positions across period boundaries to remove the seam.

## Partially done<a name="partially-done"></a>

_(none yet)_

## Resolved<a name="resolved"></a>

- [00002 — Validation rigor (purged CV, CPCV, deflated Sharpe)](00002-validation-rigor.md) — purged k-fold + embargo + CPCV (iter-9), then per-recipe PSR + the `rank` command's deflated Sharpe + PBO (iter-11) — validation rigor resolved.
- [00003 — BTC-trend regime overlay (long/cash gating)](00003-btc-regime-overlay.md) — `RegimeGatedTopkStrategy` with binary/graded/cross modes + vol-targeting knob shipped in iter-12 (spec `00011`); demo recipe `regime_steady`; exposure via `get_risk_degree`.
