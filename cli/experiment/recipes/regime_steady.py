"""regime_steady recipe — steady's book + binary-200-day MA regime gate + walk-forward holdout.

Thesis: on daily klines over 19 survivor-biased majors, ``steady``'s GBDT/Alpha158 ranker shows a
positive CPCV out-of-sample Sharpe on 2020-2024 that inverts to negative on the 2025-2026 holdout
(PBO = 0.91), strongly suggesting a market-regime mismatch rather than an over-fit model. Adding a
binary regime gate — long-only when BTC is above its 200-day SMA, flat otherwise — should filter
the worst drawdown periods without requiring any look-ahead or re-labelling.

Specifically: ``regime_steady`` keeps *all* of ``steady``'s levers (5-day label, diversified 10-name
sticky book, regularized LGBM) and adds the ``RegimeGatedTopkStrategy`` in ``binary`` mode with a
200-day MA on BTCUSDT, vol-targeting off. Walk-forward retraining is enabled (``wf_enabled=True``):
the holdout is produced by retraining each quarter on an expanding window rather than one fit over
the whole train segment, so the model tracks the regime shift instead of being frozen at 2023.

This is a falsifiable hypothesis. The honest verdict is the CPCV out-of-sample Sharpe
distribution + PSR/DSR/PBO and the holdout drawdown (``zcrypto experiment --recipe regime_steady``
then ``zcrypto rank``). If the regime gate does not improve on ``steady`` on those metrics, that is
itself a real finding.

**Measured (2025-2026 holdout, current data — iter-12 validation): the gate did not help.**
``regime_steady`` is the worst of the three on the holdout — ending ~3,477 USDT vs ``steady``
~3,551 vs ``skeleton`` ~3,664; absolute Sharpe -0.68 vs -0.67 vs -0.63; holdout PSR 0.152 vs
0.158 vs 0.174 — and PBO across the three trials is 0.99. The 2025-2026 holdout was mostly
risk-on (BTC above its 200-day MA), so the binary gate rarely engaged, and walk-forward
retraining on the same Alpha158/LGBM signal still produced a negative holdout. The honest
lesson: the scaffold extensions work and are validated, but on this survivor-biased
universe/period the signal has no edge a regime gate or periodic retraining can rescue — the
CPCV(~+1.0) -> holdout(~-0.6) inversion persists.
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
