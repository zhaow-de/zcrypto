"""tsmom_voltarget recipe — iter-35 Stage-1: per-asset TSMOM gate + vol-target, A/B vs beta_null.

iter-35 Stage-1 — the per-asset trend-momentum (TSMOM) bet: VolWeightedRegimeStrategy over the
FULL 19-coin liquid universe, identical to beta_null in every dimension EXCEPT the regime gate.
beta_null uses a market-wide BTC-trend gate (binary 200d SMA); tsmom_voltarget replaces that with
a per-asset gate (trend_window=100): only coins whose close is strictly above their own 100d SMA
are included in the investable set at each rebalance. The market BTC gate is automatically disabled
by the strategy when trend_window is set.

Everything else frozen identical to beta_null: universe (full 19-coin liquid set), weight_universe,
DummyRegressor (no ML ranking), fee_preset="vip2_bnb", label Ref($close,-6)/Ref($close,-1)-1,
label_horizon_days=6, vol_target=0.50, weight_vol_lookback=30, membership_top_n=10,
membership_lookback_days=30, segments, account, benchmark, Alpha158.

What it isolates: per-asset TSMOM gating vs market-wide BTC-trend gating, with all other levers
frozen. A cost-adjusted Sharpe improvement over beta_null would indicate that per-asset momentum
filtering adds value beyond the market-level gate.

Verdict (pending — Stage-1 A/B, iter-35): not yet evaluated.
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
    name="tsmom_voltarget",
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
