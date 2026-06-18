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
- [00003 — BTC-trend regime overlay (long/cash gating)](00003-btc-regime-overlay.md) — **[Medium]** the skeleton stays fully invested; add a BTC-trend filter scaling exposure toward cash in bear/chop (+ optional vol targeting) as a new recipe.
- [00004 — Realistic execution (slippage + maker-fill)](00004-execution-slippage-fills.md) — **[Medium]** fees are modeled but fills are frictionless; add size-scaled slippage + maker-fill probability from an aggTrades sample before trusting net P&L.
- [00005 — Point-in-time universe / survivorship](00005-point-in-time-universe.md) — **[Medium]** the skeleton trades today's 19-pair universe across all history; build point-in-time membership + delisting handling to avoid survivorship-inflated results.
- [00006 — Paper-trading harness before live](00006-paper-trading-harness.md) — **[Low]** the skeleton ends at backtest; before live, add ≥3-month paper trading vs live Binance with a backtest-divergence gate (Stage 4).

## Partially done<a name="partially-done"></a>

_(none yet)_

## Resolved<a name="resolved"></a>

- [00002 — Validation rigor (purged CV, CPCV, deflated Sharpe)](00002-validation-rigor.md) — purged k-fold + embargo + CPCV (iter-9), then per-recipe PSR + the `rank` command's deflated Sharpe + PBO (iter-11) — validation rigor resolved.
