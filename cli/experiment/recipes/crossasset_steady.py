"""crossasset_steady recipe — steady book + cross-asset features prepended to Alpha158.

**A/B hypothesis:** does injecting cross-asset information (relative strength vs BTC,
rolling beta to BTC, BTC lead-lag correlation, cointegration-deviation z-score, and
cross-sectional momentum/volatility rank) that Alpha158 structurally lacks carry
additional edge, holding steady's book, model, label, universe, and fees constant?

The cross-asset features ride on Alpha158 via ``CrossAssetProcessor`` — prepended as
the first ``infer_processor`` so the subsequent ``RobustZScoreNorm`` normalizes both
Alpha158's native factors and the appended cross-asset columns on the same scale.
``feature_config`` stays ``Alpha158``; the handler class is unchanged.

**Falsifiable test:** run both ``steady`` and ``crossasset_steady`` under CPCV; compare
out-of-sample Sharpe distribution, PSR/DSR, PBO, and holdout drawdown. The cross-asset
features win only if the CPCV Sharpe is materially higher *and* PBO < 0.5 on the
holdout — not merely better in-sample. If they do not outperform, that is itself a
real finding: the cross-asset co-movement signal (vs BTC) adds no incremental edge
beyond what Alpha158 already captures from each instrument's own OHLCV history.
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
