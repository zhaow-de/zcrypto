import math

import numpy as np
import pandas as pd

from cli.example.config import INSTRUMENTS, WINDOW
from cli.example.dataset import build_provider
from cli.example.workflow import run_experiment


def _synthetic_csv(path):
    rng = np.random.default_rng(0)
    dates = pd.date_range(WINDOW[0], WINDOW[1], freq="D")
    rows = []
    for i, sym in enumerate(INSTRUMENTS):
        price = 100.0 + i * 10
        for d in dates:
            price = max(1.0, price * (1 + rng.normal(0, 0.02)))
            rows.append((d.strftime("%Y-%m-%d"), sym, price, price * 1.01, price * 0.99, price, rng.uniform(1000, 2000)))
    cols = ["date", "symbol", "open", "high", "low", "close", "volume"]
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)
    return path


def test_run_experiment_returns_finite_metrics(tmp_path):
    csv = _synthetic_csv(tmp_path / "synthetic.csv")
    provider = build_provider(csv, tmp_path / "qlib_data")
    exp_uri = (tmp_path / "mlruns").as_uri()

    metrics = run_experiment(provider, exp_uri)

    for key in ["strategy_absolute", "excess_return_with_cost", "excess_return_without_cost"]:
        for m in ["annualized_return", "information_ratio", "max_drawdown"]:
            assert math.isfinite(metrics[key][m]), f"{key}/{m} not finite"
