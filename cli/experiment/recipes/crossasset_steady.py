"""crossasset_steady recipe — vs ``steady``, ``CrossAssetProcessor`` is prepended (rel-strength vs BTC, rolling
beta, BTC lead-lag corr, cointegration-deviation z, cross-sectional momentum/vol rank); ``feature_config``
stays Alpha158.

iter-13 (single-run), iter-14 (multi-seed), iter-26 (ungated stress sub-finding) — tests whether cross-asset
co-movement info that Alpha158 structurally lacks adds incremental edge. A/B against ``steady``; everything
else is ``steady``'s book verbatim (book, model, label, universe, fees), so the comparison isolates the
cross-asset features. ``CrossAssetProcessor`` is the first ``infer_processor`` so its appended columns are
normalized by ``RobustZScoreNorm`` on the same scale as Alpha158's native factors.

Verdict (two lenses): (a) 16-seed multi-seed holdout, 2025-26 (iter-14): BEST mean of the four — Sharpe −0.43
± 0.14, ending ~4,507 USDT, PSR 0.27; the only separation beyond seed noise is vs ``steady`` (z ≈ 1.1,
modest), vs ``skeleton`` within noise (z ≈ 0.6) — real-but-modest, not clearly above the strongest baseline.
iter-13's single-run #1 (ending ~5,027, abs Sharpe −0.34, PSR 0.310) was partly seed luck. (b) OOS-stress,
across-window mean (iter-33 sweep): 0.180 (ungated group) — marginally beats ``steady`` ungated (+0.026,
within noise), best ungated feature book, but the gate erases the difference (iter-26).
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="crossasset_steady",
    feature_config={"class": "Alpha158", "module_path": "qlib.contrib.data.handler"},
    handler_kwargs={
        # CrossAssetProcessor FIRST so its appended features are later normalized by
        # RobustZScoreNorm on the same scale as Alpha158's native factors.
        "infer_processors": [
            {"class": "CrossAssetProcessor", "module_path": "cli.experiment.features.cross_asset", "kwargs": {}},
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
        # Steady's 5-day-ahead label — verbatim copy; the test guards drift.
        "label": (["Ref($close, -6)/Ref($close, -1) - 1"], ["LABEL0"]),
    },
    model_config={
        "class": "LGBModel",
        "module_path": "qlib.contrib.model.gbdt",
        "kwargs": {
            "loss": "mse",
            "num_boost_round": 1000,
            "early_stopping_rounds": 50,
            "learning_rate": 0.03,
            "num_leaves": 16,
            "max_depth": 5,
            "colsample_bytree": 0.7,
            "subsample": 0.7,
            "lambda_l1": 2.0,
            "lambda_l2": 2.0,
        },
    },
    strategy_config={
        "class": "TopkDropoutStrategy",
        "module_path": "qlib.contrib.strategy.signal_strategy",
        "kwargs": {"topk": 10, "n_drop": 1, "hold_thresh": 5},
    },
    # --- below: verbatim copy of steady (clean A/B; guarded by test) ---
    segments={
        "train": ("2020-01-01", "2023-12-31"),
        "valid": ("2024-01-01", "2024-12-31"),
        "test": ("2025-01-01", "2026-06-15"),
    },
    universe=(
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "AVAXUSDT",
        "LINKUSDT",
        "DOGEUSDT",
        "TRXUSDT",
        "DOTUSDT",
        "POLUSDT",
        "LTCUSDT",
        "ATOMUSDT",
        "UNIUSDT",
        "NEARUSDT",
        "ARBUSDT",
        "APTUSDT",
        "PEPEUSDT",
    ),
    reference_instruments=("BTCEUR", "ETHBTC"),
    account=10_000.0,
    benchmark="BTCUSDT",
    fee_preset="vip2_bnb",
    label_horizon_days=6,
    feature_lookback_days=60,
    cv_n_groups=6,
    cv_test_groups=2,
)
