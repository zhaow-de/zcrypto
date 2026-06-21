"""funding_steady recipe — vs ``steady``, ``FundingRateProcessor`` is prepended (funding level, z-score,
cross-sectional rank, MA, rate-of-change); ``feature_config`` stays Alpha158.

iter-20 (funding A/B), iter-25 (stress sub-finding), iter-33 (sweep) — tests whether perp-funding carry
(cost-of-leverage / crowding) is genuinely new info beyond OHLCV and adds edge. A/B against ``steady``;
everything else is ``steady``'s book verbatim (book, model, label, universe, fees), so the comparison isolates
the funding features. ``FundingRateProcessor`` is the first ``infer_processor`` so its appended columns are
normalized by ``RobustZScoreNorm`` on the same scale as Alpha158's native factors.

Verdict (two lenses): (a) 16-seed multi-seed holdout, paired (iter-20): funding_steady −0.424 vs ``steady``
−0.585, mean ΔSharpe +0.20, z 2.01 — the project's FIRST signal to clear the seed-noise band over baseline;
but it still loses, and the edge proved to be a defensive low-beta tilt (iter-21/25) that did not survive
market-neutral (paired Δ −0.085, z ≈ −0.8). (b) OOS-stress, 8-seed, across-window mean (iter-25/33): mean
0.149 ≈ ``steady`` 0.154, and WORSE on 2025 (−0.603 vs −0.576) — the iter-20 edge was fragile to the training
window (iter-20 trained through 2023; it does not replicate with 2024 in training). In the iter-33 sweep:
0.149 (ungated group).
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="funding_steady",
    handler_kwargs={
        # FundingRateProcessor FIRST so its appended features are later normalized by
        # RobustZScoreNorm on the same scale as Alpha158's native factors.
        "infer_processors": [
            {"class": "FundingRateProcessor", "module_path": "cli.experiment.features.funding", "kwargs": {}},
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
