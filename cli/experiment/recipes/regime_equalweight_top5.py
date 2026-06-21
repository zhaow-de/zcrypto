"""regime_equalweight_top5 recipe — gated equal-weight on the 5 mega-caps (concentration A/B).

iter-31 — tests whether further concentration into mega-caps beats the 10-major basket. Same DummyRegressor
(no selection) + same gate (binary 200d + vol_target 0.50) + topk=5 (= universe size, all held equal-weight);
the ONLY change is the universe — the 5 most-liquid mega-caps (BTC ETH BNB SOL XRP). A/B against
`regime_equalweight_majors` (the 10-major gated equal-weight basket); everything else is
`regime_equalweight_majors`'s book verbatim, so the comparison isolates the one variable — the universe.

Verdict (OOS-stress, 8-seed, per-window 2022-2025): per-window 2022 0.000 / 2023 1.663 / 2024 0.994 / 2025
−0.283 → mean 0.594 (the HIGHEST mean of all 18 recipes), worst −0.283 — but FLAGGED as concentration-OVERFIT
to the one 2025 bear (iter-31/33). The monotonic concentration was an overfitting checkpoint, so the sweep was
STOPPED ON PRINCIPLE (do not grid-search universe-N to the holdout); 0.594 sits at the
expected-max-of-18-noisy-trials ceiling and is not the deployable best.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_equalweight_top5",
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
        "class": "DummyRegressor",
        "module_path": "sklearn.dummy",
        "kwargs": {"strategy": "mean"},
    },
    strategy_config={
        "class": "RegimeGatedTopkStrategy",
        "module_path": "cli.experiment.strategies.regime",
        "kwargs": {
            "topk": 5,
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
