"""linear_steady recipe — vs ``steady``, the model swaps LGBM → Ridge(alpha=10.0) (sklearn, deterministic; runs
via the iter-27 ``_fit_predict`` seam).

iter-27 — tests whether the OOS inversion is LGBM overfitting the training regime, i.e. whether a
heavily-regularized linear model generalizes OOS better. A/B against ``steady``; everything except
``model_config`` is ``steady``'s book verbatim (features, label, book, universe, fees), so the comparison
isolates the model class. Ridge is deterministic, so its multi-seed distribution is a point.

Verdict (OOS-stress, across-window mean, iter-27/33): mean 0.168 (ungated group) ≈ ``steady`` 0.154 — REFUTED:
the linear model inverts too; the failure is in the signal, not the model class. The model axis is ruled out.

Conditional verdict: this negative is specific to the current setup (LightGBM + Alpha158, the 2025-bear
holdout); re-test if the model, feature set, universe, or regime changes — not a permanent dead end.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="linear_steady",
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
        "class": "Ridge",
        "module_path": "sklearn.linear_model",
        "kwargs": {"alpha": 10.0},
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
    label_horizon_days=6,
    feature_lookback_days=60,
    cv_n_groups=6,
    cv_test_groups=2,
)
