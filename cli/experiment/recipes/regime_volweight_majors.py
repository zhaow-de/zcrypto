"""regime_volweight_majors recipe — inverse-vol (risk-parity-lite) gated basket of the 10 majors.

iter-32 — tests whether down-weighting the more volatile names (which drag the basket) improves the tail. Same
10-major universe, same DummyRegressor (no selection), same gate (binary 200d + vol_target 0.50); the only
change is the weighting — VolWeightedRegimeStrategy weights held names by inverse 30-day trailing vol
(risk-parity-lite). A/B against `regime_equalweight_majors` (gated EQUAL-weight); everything else is
`regime_equalweight_majors`'s book verbatim, so the comparison isolates the one variable — equal vs
inverse-vol weighting.

Verdict (OOS-stress, 8-seed, per-window 2022-2025): per-window 2022 0.000 / 2023 1.198 / 2024 0.977 / 2025
−0.158 → mean 0.504, worst −0.158 — holds the mean (≈ equal-weight 0.493) and NEARLY HALVES the worst-window
drawdown (−0.158 vs −0.444) (iter-32/33). The PRINCIPLED, robust default and most-defensible deployable best
(vs top5's 0.594, which is concentration-overfit). This is the Phase-1 deliverable: BTC-trend-time an
inverse-vol-weighted basket of the 10 large-cap majors, no ML.
"""

from cli.experiment.recipes.base import Recipe

_MAJORS = (
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
)

RECIPE = Recipe(
    name="regime_volweight_majors",
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
        "class": "DummyRegressor",
        "module_path": "sklearn.dummy",
        "kwargs": {"strategy": "mean"},
    },
    strategy_config={
        "class": "VolWeightedRegimeStrategy",
        "module_path": "cli.experiment.strategies.regime",
        "kwargs": {
            "weight_universe": _MAJORS,
            "weight_vol_lookback": 30,
            "regime_mode": "binary",
            "regime_benchmark": "BTCUSDT",
            "regime_ma_window": 200,
            "vol_target": 0.50,
        },
    },
    feature_config={"class": "Alpha158", "module_path": "qlib.contrib.data.handler"},
    segments={
        "train": ("2020-01-01", "2023-12-31"),
        "valid": ("2024-01-01", "2024-12-31"),
        "test": ("2025-01-01", "2026-06-15"),
    },
    universe=_MAJORS,
    reference_instruments=("BTCEUR", "ETHBTC"),
    account=10_000.0,
    benchmark="BTCUSDT",
    fee_preset="vip2_bnb",
    label_horizon_days=6,
    feature_lookback_days=60,
    cv_n_groups=6,
    cv_test_groups=2,
)
