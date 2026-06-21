"""regime_crossasset_voltarget recipe — crossasset_steady's book + the iter-24 winning regime gate.

iter-26 stack test: does the cross-asset relative-strength signal stack with regime-timing, or is
it redundant (as funding was in iter-25)? This is crossasset_steady's book verbatim
(CrossAssetProcessor prepended) with the strategy swapped to the iter-24 best gate
(RegimeGatedTopkStrategy, binary 200-day MA + vol-targeting at 0.50). A/B vs crossasset_steady
(ungated) and regime_voltarget (gated plain book) isolates whether cross-asset features carry
anything orthogonal to the gate's beta-timing.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_crossasset_voltarget",
    feature_config={"class": "Alpha158", "module_path": "qlib.contrib.data.handler"},
    handler_kwargs={
        # CrossAssetProcessor FIRST (verbatim from crossasset_steady) so its appended features are
        # normalized by the subsequent RobustZScoreNorm on the same scale as Alpha158's factors.
        "infer_processors": [
            {"class": "CrossAssetProcessor", "module_path": "cli.experiment.features.cross_asset", "kwargs": {}},
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
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
        "class": "RegimeGatedTopkStrategy",
        "module_path": "cli.experiment.strategies.regime",
        "kwargs": {
            "topk": 10,
            "n_drop": 1,
            "hold_thresh": 5,
            "regime_mode": "binary",
            "regime_benchmark": "BTCUSDT",
            "regime_ma_window": 200,
            "vol_target": 0.50,
        },
    },
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
