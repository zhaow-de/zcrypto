"""h20_steady recipe — steady's book with a 20-day label (vs steady's 5-day).

iter-28 label-horizon sweep — does a much longer forecast horizon avoid the 5-day label's OOS inversion on
2025+? A/B against `steady`; everything except the label (`Ref(close,-21)/Ref(close,-1)-1`,
`label_horizon_days=21`) is `steady`'s book verbatim, so the comparison isolates the forecast horizon.

Verdict (OOS-stress, 8-seed, across-window mean 2022-2025): mean 0.036 — the WEAKEST of the ungated group,
below `steady`'s 0.154 — REFUTED; the inversion is horizon-invariant, 20-day if anything worse. With
`h1`/`h10` this proves the OHLCV wall is airtight across the horizon axis (iter-28/33).

Conditional verdict: this negative is specific to the current setup (LightGBM + Alpha158, the 2025-bear
holdout); re-test if the model, feature set, universe, or regime changes — not a permanent dead end.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="h20_steady",
    handler_kwargs={
        "infer_processors": [
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
        "label": (["Ref($close, -21)/Ref($close, -1) - 1"], ["LABEL0"]),
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
    label_horizon_days=21,
    feature_lookback_days=60,
    cv_n_groups=6,
    cv_test_groups=2,
)
