"""regime_equalweight_majors recipe — gated equal-weight on the 10 established large-cap majors.

iter-30 — tests whether basket QUALITY matters, i.e. whether thin/newer alts (ARB/APT/PEPE) drag the broad
basket. Same DummyRegressor (no selection) + same gate (binary 200d + vol_target 0.50) + topk=10 (= universe
size, all held equal-weight); the ONLY change is the universe — the 10 majors with full ~2020+ history. A/B
against `regime_equalweight` (the broad 19-coin gated equal-weight basket); everything else is
`regime_equalweight`'s book verbatim, so the comparison isolates the one variable — the universe.

Verdict (OOS-stress, 8-seed, per-window 2022-2025): per-window 2022 0.000 / 2023 1.418 / 2024 0.997 / 2025
−0.444 → mean 0.493, worst −0.444 — 10-major BEATS the broad 19-coin (0.382), and the worst window is better
too (iter-30/33). Basket quality is a real EV-positive lever; the arc got simpler AND better (steady 0.154 →
gate 0.311 → drop-ML 0.382 → drop-junk-alts 0.493).
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_equalweight_majors",
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
        "class": "RegimeGatedTopkStrategy",
        "module_path": "cli.experiment.strategies.regime",
        "kwargs": {
            "topk": 10,
            "n_drop": 1,
            "hold_thresh": 5,
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
