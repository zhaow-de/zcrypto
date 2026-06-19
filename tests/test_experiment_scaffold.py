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
from cli.experiment.recipes.base import resolve_recipe
from cli.experiment.scaffold import run_experiment, strategy_config_with_signal
from cli.experiment.strategies.regime import regime_exposure_series

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

    # Fractional-trading sanity: with trade_unit=None, at least one holding should
    # have a non-integer amount.  Under the old trade_unit=1 bug every amount was
    # floored to a whole number (BTC/ETH would be zeroed on a $10k account).
    # Each value in result.positions is a qlib Position object; the inner dict of
    # holdings lives at pos.position (keyed by symbol + "cash"/"now_account_value").
    all_amounts: list[float] = []
    for pos in result.positions.values():
        inner = getattr(pos, "position", None)
        if not isinstance(inner, dict):
            continue
        for sym, details in inner.items():
            if sym in ("cash", "now_account_value") or not isinstance(details, dict):
                continue
            amt = details.get("amount")
            if amt is not None:
                all_amounts.append(float(amt))
    assert any(abs(a - round(a)) > 1e-6 for a in all_amounts), (
        "Expected at least one fractional holding; got only whole-number amounts — trade_unit may have reverted to 1"
    )

    assert (out_dir / "mlruns").exists()
    assert (data_dir / "features_cache").exists() or (data_dir / "dataset_cache").exists()
    assert (data_dir / ".experiment_cache_fingerprint").exists()


def test_seam_preserves_skeleton_strategy_class():
    """Phase-A seam smoke: strategy_config_with_signal round-trips the skeleton class name."""
    sc = resolve_recipe("skeleton").strategy_config
    built = strategy_config_with_signal(sc, "dummy_signal")
    assert built["class"] == "TopkDropoutStrategy"


def test_phase_a_regime_steady_runs_and_gate_engages(tmp_path):
    """Phase-A integration: regime_steady completes + BTC regime gate yields 0.0 on a downtrend.

    The fixture (2023-01-02 to 2024-06-28, ~544 trading days) contains a sustained BTC downtrend
    (peak ~22k down to ~14k, -39% peak-to-trough). A 20-day MA window — not the production 200-day
    window — is used here to keep the exposure assertion fixture-length-independent; this test guards
    wiring, not the production hyperparameter.
    """
    import numpy as np

    # --- 1. Seam assertion: resolve_recipe returns the right class ---
    sc = resolve_recipe("regime_steady").strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"

    # --- 2. Regime gate assertion: exposure series yields 0.0 somewhere on the fixture's BTC close ---
    # Read the raw BTCUSDT close from the committed fixture provider dir (no qlib init needed).
    close_bin = PROVIDER / "features" / "btcusdt" / "close.day.bin"
    raw = np.frombuffer(close_bin.read_bytes(), dtype="<f4")
    # qlib binary format: first element is a 0.0 placeholder; data starts at index 1.
    close_vals = raw[1:].astype("float64")
    cal_lines = (PROVIDER / "calendars" / "day.txt").read_text().strip().splitlines()
    import pandas as pd

    btc_close = pd.Series(close_vals, index=pd.to_datetime(cal_lines))

    # Use ma_window=20 (not production 200) so the test works on a ~544-day fixture.
    exposure = regime_exposure_series(btc_close, mode="binary", ma_window=20)
    assert (exposure == 0.0).any(), "Expected at least one 0.0 (risk-off) day with ma_window=20 on the fixture BTC downtrend"

    # --- 3. End-to-end smoke: regime_steady runs and produces finite metrics ---
    data_dir = tmp_path / "provider"
    shutil.copytree(PROVIDER, data_dir)
    out_dir = tmp_path / "out"

    recipe = dataclasses.replace(resolve_recipe("regime_steady"), segments=_FIXTURE_SEGMENTS)
    result = run_experiment(recipe, data_dir=data_dir, out_dir=out_dir, refresh_cache=True)

    for key in ["strategy_absolute", "excess_return_with_cost", "excess_return_without_cost"]:
        for m in ["annualized_return", "information_ratio", "max_drawdown"]:
            assert math.isfinite(result.metrics[key][m]), f"regime_steady: {key}/{m} not finite"

    assert result.ending_value > 0
