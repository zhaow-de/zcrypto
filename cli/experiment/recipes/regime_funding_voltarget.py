"""regime_funding_voltarget recipe — funding_steady's book + the iter-24 winning regime gate.

iter-25 — tests whether regime-timing stacks additively with the funding signal, or whether the two are
redundant. This is `funding_steady`'s book verbatim (FundingRateProcessor prepended) with the strategy swapped
to the iter-24 best gate (RegimeGatedTopkStrategy, binary 200-day MA + vol-targeting at 0.50). A/B against
`regime_voltarget` (the gated plain book) and `funding_steady` (the ungated funding book); everything else is
`regime_voltarget`'s book verbatim, so the comparison isolates the one variable — whether funding carries
anything orthogonal to the gate's beta-timing.

Verdict (OOS-stress, 8-seed, per-window 2022-2025): mean 0.241 (slow-gate family) — REDUNDANT/HARMFUL, worse
than `regime_voltarget` 0.311 by −0.070 (worse on 2023/2024/2025); funding adds nothing orthogonal to the
gate's beta-timing and drags the gated book (iter-25/33). Confirms iter-21: funding's edge was a defensive
beta tilt, redundant with explicit regime-timing.

Conditional verdict: this negative is specific to the current setup (LightGBM + Alpha158, the 2025-bear
holdout); re-test if the model, feature set, universe, or regime changes — not a permanent dead end.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_funding_voltarget",
    handler_kwargs={
        # FundingRateProcessor FIRST (verbatim from funding_steady) so its appended features are
        # normalized by the subsequent RobustZScoreNorm on the same scale as Alpha158's factors.
        "infer_processors": [
            {"class": "FundingRateProcessor", "module_path": "cli.experiment.features.funding", "kwargs": {}},
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
