"""basis_froth recipe — beta_null + basis-froth de-risk overlay.

iter-39 Stage-2: tests whether the perp-spot basis (a leverage/crowding proxy) adds timing
value when composed as a de-risk overlay on top of the beta_null yardstick.  The ONLY change
vs beta_null is the three froth kwargs wired into VolWeightedRegimeStrategy._mult_for:
  - froth_field="$basis"  → the perp premium over the index, ingested in iter-38
  - froth_lookback=90     → 90-day rolling z-score window
  - froth_z_threshold=1.5 → z > 1.5 triggers de-risk (leveraged-long froth)
  - froth_derisk_mult=0.0 → full cash when frothy (binary de-risk)

Everything else (universe, gate, vol_target, fee_preset, label, segments) is frozen from
beta_null so the A/B isolates the overlay.  Verdict pending: evaluate with
`zcrypto stress --recipe basis_froth --null beta_null`.
"""

from cli.experiment.recipes.base import Recipe

_FULL_LIQUID = (
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
)

RECIPE = Recipe(
    name="basis_froth",
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
            "weight_universe": _FULL_LIQUID,
            "weight_vol_lookback": 30,
            "regime_mode": "binary",
            "regime_benchmark": "BTCUSDT",
            "regime_ma_window": 200,
            "vol_target": 0.50,
            "membership_top_n": 10,
            "membership_lookback_days": 30,
            "froth_field": "$basis",
            "froth_lookback": 90,
            "froth_z_threshold": 1.5,
            "froth_derisk_mult": 0.0,
        },
    },
    feature_config={"class": "Alpha158", "module_path": "qlib.contrib.data.handler"},
    segments={
        "train": ("2020-01-01", "2023-12-31"),
        "valid": ("2024-01-01", "2024-12-31"),
        "test": ("2025-01-01", "2026-06-15"),
    },
    universe=_FULL_LIQUID,
    reference_instruments=("BTCEUR", "ETHBTC"),
    account=10_000.0,
    benchmark="BTCUSDT",
    fee_preset="vip2_bnb",
    label_horizon_days=6,
    feature_lookback_days=60,
    cv_n_groups=6,
    cv_test_groups=2,
)
