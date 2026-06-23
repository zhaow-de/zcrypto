"""derivatives_steady recipe — vs ``steady``, ``DerivativesProcessor`` is prepended (per-field
level, change, cross-sectional rank, z-score for $oi, $oi_value, $ls_top, $ls_global,
$taker_ratio, $basis; plus derived oi_confirm and smart_div); ``feature_config`` stays Alpha158.

iter-45 — tests whether an LGBModel can extract cross-sectional alpha by combining all six
derivatives fields as features (non-linear / interaction), where the hand-crafted single-factor
tilts (iter-39–44) could not. A/B against ``steady``; everything else is ``steady``'s book verbatim
(model, label, strategy, segments, universe, fees), so the comparison isolates the derivatives
features' ML contribution. ``DerivativesProcessor`` is the first ``infer_processor`` so its
appended columns are normalized by ``RobustZScoreNorm`` on the same scale as Alpha158's native
factors. Verdict pending.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="derivatives_steady",
    handler_kwargs={
        # DerivativesProcessor FIRST so its appended features are later normalized by
        # RobustZScoreNorm on the same scale as Alpha158's native factors.
        "infer_processors": [
            {"class": "DerivativesProcessor", "module_path": "cli.experiment.features.derivatives", "kwargs": {}},
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
        # Lever 1: 5-day-ahead return (close[t+6]/close[t+1] - 1) replacing
        # Alpha158's 2-day default (close[t+2]/close[t+1] - 1). Overrides
        # Alpha158.get_label_config() via the ``label`` kwarg; the format mirrors
        # that method's (expressions, names) return. The max forward Ref here is
        # 6, which MUST equal label_horizon_days below for a leak-free CPCV purge.
        "label": (["Ref($close, -6)/Ref($close, -1) - 1"], ["LABEL0"]),
    },
    model_config={
        # Lever 3: more regularized than ``skeleton`` (lr .05->.03, max_depth
        # 8->5, num_leaves 31->16, l1/l2 1->2, sub/col .8->.7) — trade in-sample
        # fit for out-of-sample generalization, which is what CPCV/PBO reward.
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
    # Lever 2: diversified + sticky book to cut the dominant after-cost term at
    # 12 bps. topk=10 holds ~half the universe; hold_thresh=5 blocks selling a
    # name held fewer than 5 days.
    strategy_config={
        "class": "TopkDropoutStrategy",
        "module_path": "qlib.contrib.strategy.signal_strategy",
        "kwargs": {"topk": 10, "n_drop": 1, "hold_thresh": 5},
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
    # Lever 1 cont'd: purge the full 5-day label horizon in CPCV (matches the max
    # forward Ref in the label above). feature_lookback_days stays at Alpha158's
    # longest window (60), same as skeleton.
    label_horizon_days=6,
    feature_lookback_days=60,
    cv_n_groups=6,
    cv_test_groups=2,
)
