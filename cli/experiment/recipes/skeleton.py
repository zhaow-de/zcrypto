"""skeleton recipe — the naive baseline itself (Alpha158 + LGBM, topk=5 / n_drop=1, 2-day default label, no
hold_thresh).

baseline — a single GBDT on Alpha158, churning a 5-name book daily, is the naive reference book that
``steady`` and friends A/B against. It is not compared to anything upstream; it is the upstream. Measured at
iter-14.

Verdict (16-seed multi-seed holdout, 2025-26, 12bps): Sharpe −0.51 ± 0.15, ending ~4,329 USDT, PSR 0.23 —
2nd-best of the four early recipes and the most stable. True 4-recipe order is ``crossasset_steady`` >
``skeleton`` > ``alpha360_steady`` > ``steady``, which inverts iter-13's single-run order (that was seed
luck). All four lose ~55-64%. NOT in the iter-33 18-recipe OOS-stress sweep — its verdict is
holdout/multi-seed only (iter-14).
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="skeleton",
    handler_kwargs={
        "infer_processors": [
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
    },
    model_config={
        "class": "LGBModel",
        "module_path": "qlib.contrib.model.gbdt",
        "kwargs": {
            "loss": "mse",
            "num_boost_round": 1000,
            "early_stopping_rounds": 50,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "max_depth": 8,
            "colsample_bytree": 0.8,
            "subsample": 0.8,
            "lambda_l1": 1.0,
            "lambda_l2": 1.0,
        },
    },
    strategy_config={
        "class": "TopkDropoutStrategy",
        "module_path": "qlib.contrib.strategy.signal_strategy",
        "kwargs": {"topk": 5, "n_drop": 1},
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
)
