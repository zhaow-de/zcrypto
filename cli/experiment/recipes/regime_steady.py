"""regime_steady recipe — steady's book + a binary 200-day-MA BTC-trend regime gate (plus walk-forward
retraining).

iter-23 (gate fixed; built iter-12) — tests whether a binary long/cash gate (long only when BTC > its 200-day
SMA, flat otherwise) filters the worst drawdowns, i.e. that `steady`'s CPCV(+1.0) -> holdout(-0.63), PBO 0.91
inversion is a regime mismatch rather than an overfit model. A/B against `steady`; everything else is
`steady`'s book verbatim (5-day label, diversified 10-name sticky book, regularized LGBM) plus
`RegimeGatedTopkStrategy` binary mode with vol_target off and quarterly expanding-window walk-forward
retraining, so the comparison isolates the regime gate.

Verdict (OOS-stress, 8-seed, across-window mean 2022-2025): mean 0.289 (slow-gate family), worst -0.220 —
Pareto-better than `steady`'s 0.154 / -0.753: full-cash avoids the 2022 crash (0.000 vs -0.753) and halves the
2025 loss. The FIRST OOS-robust improvement in the project — defensive market-timing, not new alpha
(iter-23/33). (iter-12's single-run "gate did not help" was a false negative — the gate was inert due to a
sizing bug that never consulted it.)
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_steady",
    handler_kwargs={
        # Identical to steady: same normalization + 5-day-ahead label so A/B isolates the regime gate.
        "infer_processors": [
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
        # 5-day-ahead return — identical to steady; max forward Ref is 6, matching label_horizon_days.
        "label": (["Ref($close, -6)/Ref($close, -1) - 1"], ["LABEL0"]),
    },
    model_config={
        # Identical to steady's regularized LGBM — isolates the regime overlay as the single change.
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
            "vol_target": None,
        },
    },
    feature_config={"class": "Alpha158", "module_path": "qlib.contrib.data.handler"},
    # --- below: identical to steady (clean A/B; guarded by tests) ---
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
    # Walk-forward holdout: retrain each quarter on an expanding window (CPCV stays unchanged
    # and still runs before the holdout for the OOS Sharpe distribution).
    wf_enabled=True,
    wf_retrain_freq="quarter",
    wf_window="expanding",
)
