"""alpha360_steady recipe — vs ``steady``, the feature handler swaps Alpha158 → Alpha360 (~360 raw OHLCV-derived
features).

iter-13 (single-run), iter-14 (multi-seed) — tests whether more raw OHLCV dimensions carry additional edge
(prior: NO — redundant transforms add curse-of-dimensionality overfit). A/B against ``steady``; everything
else is ``steady``'s book verbatim (book, model, label, universe, fees), so the comparison isolates the
feature handler. Alpha360.__init__ accepts the ``label`` kwarg via the same ``**kwargs`` pop mechanism as
Alpha158, so steady's 5-day label override is fully supported.

Verdict (16-seed multi-seed holdout, 2025-26): middling — Sharpe −0.57 ± 0.17, ending ~3,827 USDT, PSR 0.20 —
NOT the worst (``steady`` is); iter-13's single-run "worst" ranking (ending ~3,389, abs Sharpe −0.69, PSR
0.149) was seed noise. More raw OHLCV dims gave no edge over Alpha158; all four lose (iter-14). NOT in the
iter-33 18-recipe OOS-stress sweep — its verdict is holdout/multi-seed only.

Conditional verdict: this negative is specific to the current setup (LightGBM + Alpha158, the 2025-bear
holdout); re-test if the model, feature set, universe, or regime changes — not a permanent dead end.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="alpha360_steady",
    feature_config={"class": "Alpha360", "module_path": "qlib.contrib.data.handler"},
    handler_kwargs={
        # Identical normalization to steady so the A/B isolates the feature handler
        # (not preprocessing differences).
        "infer_processors": [
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
        # Steady's 5-day-ahead label; overrides Alpha360.get_label_config() via the
        # ``label`` kwarg (confirmed accepted — same **kwargs pop mechanism as Alpha158).
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
        "class": "TopkDropoutStrategy",
        "module_path": "qlib.contrib.strategy.signal_strategy",
        "kwargs": {"topk": 10, "n_drop": 1, "hold_thresh": 5},
    },
    # --- below: verbatim copy of steady (clean A/B; guarded by test) ---
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
