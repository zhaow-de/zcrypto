"""regime_voltarget recipe — steady's book + binary 200-day gate WITH vol-targeting.

iter-24 — tests whether scaling exposure down in violent regimes the plain binary gate ignores adds defense
and recovers a little bull exposure. On top of the binary long/cash gate, gross exposure is trimmed when BTC's
30-day annualized realized vol exceeds the 0.50 target (mult *= clip(vol_target/realized, <=1)). A/B against
`regime_steady`; everything else is `regime_steady`'s book verbatim (which is steady's book under the gate),
so the comparison isolates the one variable — adding vol-targeting on top of the binary 200d gate.

Verdict (OOS-stress, 8-seed, per-window 2022-2025): per-window 2022 0.000 / 2023 0.925 / 2024 0.543 / 2025
−0.223 → mean 0.311, worst −0.223 — the (slim) best GATE-on-Alpha158, +0.022 over `regime_steady` 0.289
(small/possibly-noise) (iter-24/29/33). This is the "Alpha158 + gate" arm that gated-equal-weight later BEAT,
establishing that the ML selection is net-harmful (iter-29).
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_voltarget",
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
            "regime_mode": "binary",
            "regime_benchmark": "BTCUSDT",
            "regime_ma_window": 200,
            "vol_target": 0.50,
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
