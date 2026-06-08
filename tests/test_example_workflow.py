import logging
import math
from pathlib import Path

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


def test_run_experiment_returns_finite_metrics(tmp_path, caplog, capfd):
    caplog.set_level(logging.INFO, logger="qlib.workflow")

    csv = _synthetic_csv(tmp_path / "synthetic.csv")
    provider = build_provider(csv, tmp_path / "qlib_data")
    exp_uri = (tmp_path / "mlruns").as_uri()

    cwd_before = Path.cwd()
    metrics = run_experiment(provider, exp_uri)
    # Regression guard for qlib 0.9.7's MLflowExpManager FileLock bug — see workflow.py.
    assert Path.cwd() == cwd_before, "run_experiment must restore cwd"
    assert not (cwd_before / "private").exists(), "qlib leaked relative-path scaffolding into cwd"

    # Regression guard: the chdir-into-tempdir put qlib's _log_uncommitted_code (recorder.py:378)
    # outside a git repo. Without the `git init` inside the tempdir, qlib emits three INFO records
    # and leaks raw `git: not a git repository` usage text straight to stderr.
    noisy = [r.getMessage() for r in caplog.records if "Fail to log the uncommitted code" in r.getMessage()]
    assert not noisy, f"qlib git-snapshot fallback fired: {noisy}"
    captured = capfd.readouterr()
    assert "Not a git repository" not in captured.err, "raw git stderr leaked"
    assert "git diff --no-index" not in captured.err, "raw git stderr leaked"

    for key in ["strategy_absolute", "excess_return_with_cost", "excess_return_without_cost"]:
        for m in ["annualized_return", "information_ratio", "max_drawdown"]:
            assert math.isfinite(metrics[key][m]), f"{key}/{m} not finite"
