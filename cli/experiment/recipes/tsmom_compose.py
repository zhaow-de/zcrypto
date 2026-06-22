"""tsmom_compose recipe — iter-37: per-asset selection COMPOSED on top of the market gate.

iter-35/36 refuted per-asset trend gating when it *replaces* the market gate (100d whipsaws on bear
bounces; 200d holds alts into the crash). This recipe instead **composes**: it keeps beta_null's
BTC-200d market gate (full cash in a BTC-bear — the proven defense) AND adds a per-asset 100d trend
filter that, in non-bear, holds only the coins above their own 100d SMA. The 100d whipsaw that sank
iter-35 cannot fire here — in a BTC-bear the whole basket is already cashed by the market gate.

Identical to tsmom_voltarget EXCEPT `compose_market_gate=True` (which re-activates the market gate that
trend_window otherwise disables). Everything else frozen identical to beta_null: universe (full 19-coin
liquid set), DummyRegressor, fee_preset="vip2_bnb", label Ref($close,-6)/Ref($close,-1)-1,
label_horizon_days=6, vol_target=0.50, weight_vol_lookback=30, membership_top_n=10,
membership_lookback_days=30, trend_window=100, segments, account, benchmark, Alpha158.

What it isolates: does per-asset trend SELECTION add bull-side value on top of the (bear-defended) basket?
A cost-adjusted delta-vs-null > 0 would be the first Stage-1 improvement over the passive-beta null.

Verdict (pending — iter-37 A/B): not yet evaluated.
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
    name="tsmom_compose",
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
            "trend_window": 100,
            "compose_market_gate": True,
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
