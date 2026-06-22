"""tsmom_voltarget_w200 recipe — iter-36: per-asset TSMOM at the 200d window, A/B vs beta_null.

iter-36 (T0022 first follow-up). iter-35 refuted per-asset trend gating at a 100d window
(`tsmom_voltarget` lost to beta_null, mean delta −0.427, bear whipsaw). This variant is identical to
`tsmom_voltarget` EXCEPT `trend_window=100 → 200` — matching beta_null's market-gate window. It isolates
"per-asset vs market gate at the SAME speed": if it ties beta_null, per-asset granularity is neutral; if
it still loses, per-asset granularity itself whipsaws (and per-asset trend gating is a dead sub-channel —
a shelve call parked for the human).

Everything else frozen identical to `tsmom_voltarget` / beta_null: universe (full 19-coin liquid set),
weight_universe, DummyRegressor, fee_preset="vip2_bnb", label Ref($close,-6)/Ref($close,-1)-1,
label_horizon_days=6, vol_target=0.50, weight_vol_lookback=30, membership_top_n=10,
membership_lookback_days=30, segments, account, benchmark, Alpha158.

Verdict (pending — iter-36 A/B): not yet evaluated.
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
    name="tsmom_voltarget_w200",
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
            "trend_window": 200,
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
