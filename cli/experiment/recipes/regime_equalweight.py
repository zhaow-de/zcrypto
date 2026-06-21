"""regime_equalweight recipe — a NO-SELECTION book (hold the whole 19-coin universe equal-weight) under the gate.

iter-29 — tests how much of the gated edge is Alpha158 cross-sectional SELECTION vs pure BTC-trend
market-timing (selection vs none). ML selection is removed: a DummyRegressor(strategy=mean) emits a constant
signal (no ranking; runs via the iter-27 _fit_predict generic branch) and RegimeGatedTopkStrategy with topk=19
holds all names equal-weight. A/B against `regime_voltarget` (Alpha158 top-10 + same gate); everything else is
`regime_voltarget`'s book verbatim — same gate (binary 200d + vol_target 0.50) — so the comparison isolates
the one variable — selection vs none.

Verdict (OOS-stress, 8-seed, per-window 2022-2025): per-window 2022 0.000 / 2023 1.058 / 2024 1.100 / 2025
−0.632 → mean 0.382, worst −0.632 — gated EQUAL-WEIGHT BEATS gated Alpha158 selection (0.311), so the ML
cross-sectional selection has NEGATIVE mean OOS value (≈ −0.07): the pipeline is net-harmful vs holding the
gated basket, giving up the broad 2024 rally (0.54 vs 1.10), though selection does help the 2025 tail (−0.22
vs −0.63) (iter-29). Reframes the project — the deployable edge is market-timing, not stock-picking.
"""

from cli.experiment.recipes.base import Recipe

RECIPE = Recipe(
    name="regime_equalweight",
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
            "topk": 19,
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
