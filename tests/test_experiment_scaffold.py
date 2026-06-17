"""Integration test for the experiment scaffold (train -> backtest -> extract).

This is the slow test: it runs a full qlib backtest against the committed
synthetic fixture. It requires a running Redis (qlib's Disk*Cache locks) and is
skipped when Redis is unreachable.
"""

from __future__ import annotations

import dataclasses
import math
import os
import shutil
from pathlib import Path

import pytest

from cli.experiment.recipes import skeleton
from cli.experiment.scaffold import run_experiment

PROVIDER = Path(__file__).resolve().parents[1] / "cli" / "experiment" / "data" / "provider"


def _redis_up() -> bool:
    try:
        import redis

        port = int(os.environ.get("ZCRYPTO_REDIS_PORT", "6379"))
        redis.Redis(host="localhost", port=port, socket_connect_timeout=1).ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _redis_up(), reason="needs redis (scripts/redis.sh start)")

# Short segments fitting the 2023-01-02..2024-06-28 fixture, leaving ~60 trading days
# of warmup before train start (Alpha158 has ~60-day rolling windows). The test end
# stops one bar short of the calendar's last day (2024-06-28): qlib's backtest needs
# one calendar bar beyond end_time for the final step's look-ahead.
_FIXTURE_SEGMENTS = {
    "train": ("2023-03-01", "2023-12-31"),
    "valid": ("2024-01-01", "2024-02-29"),
    "test": ("2024-03-01", "2024-06-27"),
}


def test_run_experiment_against_fixture(tmp_path):
    # Copy the committed fixture so qlib's cache/ + fingerprint do not pollute the tree.
    data_dir = tmp_path / "provider"
    shutil.copytree(PROVIDER, data_dir)
    out_dir = tmp_path / "out"

    recipe = dataclasses.replace(skeleton.RECIPE, segments=_FIXTURE_SEGMENTS)

    result = run_experiment(recipe, data_dir=data_dir, out_dir=out_dir, refresh_cache=True)

    # Every metric finite.
    for key in ["strategy_absolute", "excess_return_with_cost", "excess_return_without_cost"]:
        for m in ["annualized_return", "information_ratio", "max_drawdown"]:
            assert math.isfinite(result.metrics[key][m]), f"{key}/{m} not finite"

    assert result.ending_value > 0

    assert not result.account_curve.empty
    # First account value should be one day's move away from the starting account.
    assert abs(result.account_curve.iloc[0] - recipe.account) <= recipe.account * 0.5

    assert len(result.positions) > 0

    assert (out_dir / "mlruns").exists()
    assert (data_dir / "cache").exists()
    assert (data_dir / "cache" / ".dataset_fingerprint").exists()
