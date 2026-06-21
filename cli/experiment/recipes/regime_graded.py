"""regime_graded recipe — regime_steady's binary gate replaced by a graded 200-day-MA gate (vs all-or-nothing).

iter-24 refinement — does a graded gate recover bull upside surrendered by the all-or-nothing binary winner?
Full exposure above the 200d SMA by +5%, half exposure within a +/-5% chop band, cash below -5%. A/B against
`regime_steady` (the binary winner); everything else is `steady`'s book verbatim, only the gate mode changes
binary -> graded, so the comparison isolates the gating curve.

Verdict (OOS-stress, 8-seed, across-window mean 2022-2025): mean 0.259 (slow-gate family) — WORSE than binary
`regime_steady`'s 0.289 and `regime_voltarget`'s 0.311; the +/-5% chop band keeps partial exposure THROUGH the
2022 crash (-0.658 vs full-cash 0.000), blowing up the worst case. The binary full-cash-in-bear is the
load-bearing mechanism; graded is net-negative (iter-24/33).

Conditional verdict: this negative is specific to the current setup (LightGBM + Alpha158, the 2025-bear
holdout); re-test if the model, feature set, universe, or regime changes — not a permanent dead end.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_graded",
    handler_kwargs={
        "infer_processors": [
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
            "regime_mode": "graded",
            "regime_benchmark": "BTCUSDT",
            "regime_ma_window": 200,
            "regime_band": 0.05,
            "chop_exposure": 0.5,
            "vol_target": None,
        },
    },
    feature_config={"class": "Alpha158", "module_path": "qlib.contrib.data.handler"},
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
