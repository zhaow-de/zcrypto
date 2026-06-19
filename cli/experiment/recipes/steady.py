"""Steady recipe — diversified, low-turnover, regularized LightGBM/Alpha158.

Thesis (vs ``skeleton``): on daily klines, long-only, over 19 survivor-biased
majors at 12 bps round-trip fees, a single GBDT on Alpha158 has only a weak
edge — so the ``skeleton`` baseline (a 2-day signal churning a 5-name book
every day) bleeds most of that edge to turnover costs. ``steady`` keeps the
same data universe, segments, and fees (a clean A/B) and changes three
coordinated knobs, all aimed at *after-cost risk-adjusted* performance —
Sharpe up, drawdown down — not raw return:

1. **Longer label (Lever 1).** Predict the 5-day-ahead return instead of the
   2-day default. A smoother target raises the signal-to-noise for the ranker
   and makes its predictions change more slowly, so the book turns over less on
   its own. ``label_horizon_days`` is bumped to 6 to match the label's max
   forward reference, keeping the CPCV purge leak-free (see docs/specs/00008).

2. **Diversified, sticky book (Lever 2).** ``topk`` 5 -> 10 holds ~half the
   19-pair universe, so idiosyncratic volatility falls (higher Sharpe, shallower
   drawdown); ``n_drop`` stays at 1 and ``hold_thresh=5`` forbids selling a name
   held fewer than 5 days. Together these cap turnover hard — the single biggest
   after-cost lever at 12 bps.

3. **Stronger regularization (Lever 3).** Slower learning rate, shallower trees,
   heavier L1/L2, more aggressive row/column subsampling. A simpler model
   generalizes better out-of-sample, which is exactly what the CPCV Sharpe
   distribution and PBO reward; in-sample fit is irrelevant here.

This is a falsifiable hypothesis, not a promise. The honest verdict is the CPCV
out-of-sample Sharpe distribution + PSR/DSR/PBO and the holdout drawdown
(``zcrypto experiment --recipe steady`` then ``zcrypto rank``). If ``steady``
does not beat ``skeleton`` on those, that is itself a real finding.

**Measured (2025-2026 holdout, current data — PR #41): the hypothesis did not
pan out.** ``steady`` does *not* beat ``skeleton`` — marginally worse holdout
Sharpe / PSR / excess-vs-BTC, and both lose ~63-66%. Both also show a positive
CPCV out-of-sample Sharpe on 2020-2024 (~+1.0) that inverts to negative on the
holdout (~-0.63), with PBO = 0.91: a market-regime mismatch that recipe-only
tuning cannot fix. The lever that could is the BTC-regime overlay — open-topic
T0003 (scaffold-level), not another recipe.

The non-lever fields below (universe, segments, fees, account, benchmark,
reference_instruments, feature_lookback_days, cv knobs) are deliberately
identical to ``skeleton`` so the comparison is a clean A/B; the
``test_steady_matches_skeleton_ab_controls`` test guards against drift.
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
