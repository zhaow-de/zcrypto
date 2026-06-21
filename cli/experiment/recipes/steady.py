"""steady recipe — vs ``skeleton``, three coordinated knobs at once: a 5-day label
(``Ref(close,-6)/Ref(close,-1)-1``, ``label_horizon_days=6``), a diversified sticky book (topk 5→10,
``hold_thresh=5``), and stronger regularization (lr .05→.03, depth 8→5, leaves 31→16, L1/L2 1→2, sub/col
.8→.7).

iter-12/13 (built), iter-14 (multi-seed), iter-29 (stress baseline) — tests whether a lower-turnover,
diversified, regularized book bleeds less edge to 12bps fees and generalizes better OOS. A/B against
``skeleton``; everything else is ``skeleton``'s book verbatim (universe, segments, fees), so the comparison
isolates the label + book + model bundle. The ``test_steady_matches_skeleton_ab_controls`` test guards the
non-lever fields against drift.

Verdict (two lenses): (a) 16-seed multi-seed holdout, 2025-26 (iter-14): WORST of the four by mean — Sharpe
−0.62 ± 0.21, ending ~3,641 USDT, PSR 0.19, widest spread; the low-turnover book did not help OOS. (b)
OOS-stress, 8-seed, per-window 2022-2025 (iter-29): 2022 −0.753 / 2023 1.244 / 2024 0.700 / 2025 −0.576 → mean
0.154, worst −0.753 — the ungated baseline of the deployable progression. CPCV 2020-2024 ≈ +1.0 inverts to ≈
−0.63 on the holdout, PBO 0.91. In the iter-33 sweep: 0.154 (ungated group). The two lenses ask different
questions (the bear-only holdout vs the across-window mean that includes bull years) and do not conflict.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="steady",
    handler_kwargs={
        # Identical normalization to ``skeleton`` so the A/B isolates the label,
        # book, and model changes (not preprocessing differences).
        "infer_processors": [
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
    # --- below: identical to skeleton (clean A/B; guarded by tests) ---
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
