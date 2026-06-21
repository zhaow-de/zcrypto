"""regime_crossasset_voltarget recipe — crossasset_steady's book + the iter-24 winning regime gate.

iter-26 — tests whether the cross-asset relative-strength signal (a different signal type than funding) stacks
with regime-timing where funding did not in iter-25. This is `crossasset_steady`'s book verbatim
(CrossAssetProcessor prepended) with the strategy swapped to the iter-24 best gate (RegimeGatedTopkStrategy,
binary 200-day MA + vol-targeting at 0.50). A/B against `regime_voltarget` (the gated plain book) and
`crossasset_steady` (untested OOS); everything else is `regime_voltarget`'s book verbatim, so the comparison
isolates the one variable — whether cross-asset features carry anything orthogonal to the gate's beta-timing.

Verdict (OOS-stress, 8-seed, per-window 2022-2025): mean 0.304 (slow-gate family) ≈ `regime_voltarget` 0.311
(−0.007, flat) — REDUNDANT; cross-asset adds nothing on the gated book (iter-26/33). With iter-25 this is
CONCLUSIVE: no feature add improves the gated book; gate-on-plain-Alpha158 (~0.31) is the feature-stacking
ceiling, and the feature-stacking thread is closed.

Conditional verdict: this negative is specific to the current setup (LightGBM + Alpha158, the 2025-bear
holdout); re-test if the model, feature set, universe, or regime changes — not a permanent dead end.
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
