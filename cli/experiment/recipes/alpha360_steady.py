"""alpha360_steady recipe — steady book, Alpha360 features instead of Alpha158.

**A/B hypothesis:** does replacing Alpha158 (158 engineered factors) with Alpha360
(~360 raw OHLCV-derived features) carry additional edge, holding steady's book,
model, label, universe, and fees constant?

**Falsifiable test:** run both recipes under CPCV; compare out-of-sample Sharpe
distribution, PSR/DSR, PBO, and holdout drawdown. Alpha360 wins only if its
CPCV Sharpe is materially higher *and* PBO < 0.5 (i.e. the best CPCV fold beats
chance on the holdout).

**Honest expectation:** Alpha360 adds more dimensions but carries the same
per-instrument OHLCV information as Alpha158 — the extra columns are redundant
transformations of the same source. More dimensions with the same signal-to-noise
typically increases the curse of dimensionality; a GBDT will fit the extra
features in-sample and pay for it out-of-sample. The prior is that Alpha360 does
*not* outperform Alpha158 on this universe. The point of this recipe is to
measure, not assume.

**Label note (RECON confirmed):** Alpha360.__init__ accepts the ``label`` kwarg
via ``**kwargs`` (line 71: ``kwargs.pop("label", self.get_label_config())``) —
identical mechanism to Alpha158. The steady 5-day label override
``(["Ref($close, -6)/Ref($close, -1) - 1"], ["LABEL0"])`` is fully supported.

**Measured (2025-2026 holdout, iter-13 validation): worst of the four.** ``alpha360_steady`` ranked
last — ending ~3,389 USDT vs ``steady`` ~4,817, ``skeleton`` ~3,664, ``crossasset_steady`` ~5,027;
absolute Sharpe -0.69; PSR 0.149 — confirming the expectation that more raw OHLCV dimensions add
overfit, not edge. Caveat: holdout estimates are nondeterministic (open-topic ``T0011``), so treat the
ranking as indicative, not exact.

**Measured (multi-seed, iter-14 — 16 seeds, light-``lgb.train`` basis, 2025-2026 holdout, after 12 bps
fees): middling — Sharpe −0.57 ± 0.17, ending value ~3,827 USDT, PSR 0.20.** NOT the worst by mean
(``steady`` is); iter-13's single-run "worst" ranking was partly seed noise. More raw OHLCV dims still
gave no edge over Alpha158. All four still lose. Light-``lgb.train`` holdout path — internally
consistent across recipes but NOT directly comparable to iter-13's MLflow single-fit numbers.
``T0011`` resolved.
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
