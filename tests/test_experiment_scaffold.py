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

from cli.experiment import cpcv as _cpcv_mod
from cli.experiment.recipes import skeleton
from cli.experiment.recipes.base import resolve_recipe
from cli.experiment.scaffold import handler_config, run_experiment, strategy_config_with_signal
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


def test_walkforward_holdout_stitches_multiple_periods(tmp_path):
    """Phase-B integration: wf_enabled retrains per quarter and stitches a contiguous holdout.

    On the fixture's test window (2024-03-01..2024-06-27) quarterly walk-forward yields two
    periods (Q1 tail + Q2); the runner concatenates their per-period report_df into one
    monotonically-increasing holdout with finite metrics. Heavier than the single-fit path
    (it fits one booster per period), so it is the wf-specific smoke.
    """
    data_dir = tmp_path / "provider"
    shutil.copytree(PROVIDER, data_dir)
    out_dir = tmp_path / "out"

    recipe = dataclasses.replace(
        resolve_recipe("steady"),
        name="wf_probe",
        segments=_FIXTURE_SEGMENTS,
        wf_enabled=True,
        wf_retrain_freq="quarter",
    )
    result = run_experiment(recipe, data_dir=data_dir, out_dir=out_dir, refresh_cache=True)

    # The walk-forward path ran and stitched more than one retrain period.
    assert result.wf_periods is not None and result.wf_periods > 1

    # Stitched holdout is non-empty and contiguous (>1 period concatenated in order).
    assert len(result.report_df) > 0
    assert result.report_df.index.is_monotonic_increasing
    assert not result.report_df.index.has_duplicates

    # Metrics present (the validation outputs the report / rank consume).
    assert "strategy_absolute" in result.metrics
    for m in ["annualized_return", "information_ratio", "max_drawdown"]:
        assert math.isfinite(result.metrics["strategy_absolute"][m]), f"wf: strategy_absolute/{m} not finite"

    assert result.ending_value > 0
    assert not result.account_curve.empty
    assert result.account_curve.index.is_monotonic_increasing


def test_exchange_kwargs_realistic_default_adds_impact_and_haircut():
    from cli.experiment.recipes.base import FEE_PRESETS, resolve_recipe
    from cli.experiment.scaffold import exchange_kwargs

    r = resolve_recipe("steady")  # fees_only defaults False
    ek = exchange_kwargs(r)
    fee_open, fee_close = FEE_PRESETS[r.fee_preset]
    assert ek["impact_cost"] == r.impact_cost
    assert ek["open_cost"] == fee_open + r.maker_fill_haircut
    assert ek["close_cost"] == fee_close + r.maker_fill_haircut
    assert ek["deal_price"] == "close" and ek["trade_unit"] is None


def test_exchange_kwargs_fees_only_is_todays_behavior():
    import dataclasses

    from cli.experiment.recipes.base import FEE_PRESETS, resolve_recipe
    from cli.experiment.scaffold import exchange_kwargs

    r = dataclasses.replace(resolve_recipe("steady"), fees_only=True)
    ek = exchange_kwargs(r)
    fee_open, fee_close = FEE_PRESETS[r.fee_preset]
    assert ek["open_cost"] == fee_open and ek["close_cost"] == fee_close
    assert "impact_cost" not in ek  # raw fees-only path, byte-identical to pre-iter-19


def test_feature_seam_preserves_skeleton_handler_class():
    """Phase-A feature seam: handler_config from skeleton.feature_config yields Alpha158.

    Verifies that the pluggable-feature-handler seam (iter-13) correctly threads
    feature_config through handler_config so the skeleton recipe still produces an
    Alpha158 handler config — i.e. the seam is transparent for existing recipes.
    """
    recipe = resolve_recipe("skeleton")
    cfg = handler_config(
        recipe.feature_config,
        instruments=list(recipe.universe)[:3],
        start="2023-01-01",
        end="2023-12-31",
        fit_start="2023-01-01",
        fit_end="2023-12-31",
        handler_kwargs=recipe.handler_kwargs,
    )
    assert cfg["class"] == "Alpha158", f"Expected Alpha158, got {cfg['class']}"


def test_alpha360_steady_runs_end_to_end(tmp_path):
    """Phase-A integration: alpha360_steady completes + produces finite metrics on the fixture.

    Alpha360 (~360 raw OHLCV features) is the A/B against Alpha158 for the steady book.
    This guards that the feature_config seam threads Alpha360 correctly through qlib's
    DatasetH + handler init, and that the recipe runs without error on the fixture span.
    """
    data_dir = tmp_path / "provider"
    shutil.copytree(PROVIDER, data_dir)
    out_dir = tmp_path / "out"

    recipe = dataclasses.replace(resolve_recipe("alpha360_steady"), segments=_FIXTURE_SEGMENTS)
    result = run_experiment(recipe, data_dir=data_dir, out_dir=out_dir, refresh_cache=True)

    for key in ["strategy_absolute", "excess_return_with_cost", "excess_return_without_cost"]:
        for m in ["annualized_return", "information_ratio", "max_drawdown"]:
            assert math.isfinite(result.metrics[key][m]), f"alpha360_steady: {key}/{m} not finite"

    assert result.ending_value > 0


def test_crossasset_steady_runs_and_column_present(tmp_path):
    """Phase-A integration: crossasset_steady completes + cross-asset column appears in the feature matrix.

    Asserts three things:
    1. The end-to-end run completes and produces finite metrics.
    2. The materialized infer_df (via _materialize_span) contains a cross-asset feature
       column — specifically `rs_20` (20-day relative-strength vs BTC), whose window fits
       the fixture warmup span (~43 trading days / ~60 calendar days before train start on 2023-03-01).
    3. The run result's ending_value is positive (backtest completed, not flat).

    Note on NaN tolerance: the fixture is ~544 trading days; longer windows (beta_60, coint_z
    at 60d, leadlag at 60d) warm up slowly and may be NaN-filled on the early rows. The
    assertion guards column presence + run completion, not specific values.
    """
    # --- 1. End-to-end run ---
    data_dir = tmp_path / "provider"
    shutil.copytree(PROVIDER, data_dir)
    out_dir = tmp_path / "out"

    recipe = dataclasses.replace(resolve_recipe("crossasset_steady"), segments=_FIXTURE_SEGMENTS)
    result = run_experiment(recipe, data_dir=data_dir, out_dir=out_dir, refresh_cache=True)

    for key in ["strategy_absolute", "excess_return_with_cost", "excess_return_without_cost"]:
        for m in ["annualized_return", "information_ratio", "max_drawdown"]:
            assert math.isfinite(result.metrics[key][m]), f"crossasset_steady: {key}/{m} not finite"

    assert result.ending_value > 0

    # --- 2. Cross-asset column present in the materialized feature matrix ---
    # Re-use the same data_dir (already cache-primed by the run above) to materialise
    # just the train span and inspect the ("feature", *) columns.
    import contextlib
    import tempfile

    import qlib
    from qlib.constant import REG_US

    train_start, train_end = _FIXTURE_SEGMENTS["train"]
    with tempfile.TemporaryDirectory(prefix="zcrypto-xasset-check-") as cwd_tmp, contextlib.chdir(cwd_tmp):
        # qlib.init reinitializes module-level globals; safe here because data_dir is the
        # same cache-primed dir used by run_experiment above, so no cold-cache penalty.
        qlib.init(
            provider_uri=str(data_dir),
            region=REG_US,
            expression_cache="DiskExpressionCache",
            dataset_cache="DiskDatasetCache",
            logging_config=None,
        )
        infer_df, _ = _cpcv_mod._materialize_span(recipe, train_start, train_end)

    feat_cols = infer_df["feature"].columns.tolist()
    assert "rs_20" in feat_cols, f"Expected 'rs_20' in feature columns; got: {feat_cols}"


# ---------------------------------------------------------------------------
# iter-14: multi-seed holdout distribution + determinism (Task 5)
# ---------------------------------------------------------------------------


def test_multiseed_distribution_shape(tmp_path):
    """run_holdout_seeds returns per_seed of length N with seed key + summary with mean/std/min/max keys."""
    import json

    from cli.experiment.multiseed import run_holdout_seeds

    data_dir = tmp_path / "provider"
    shutil.copytree(PROVIDER, data_dir)

    recipe = dataclasses.replace(skeleton.RECIPE, segments=_FIXTURE_SEGMENTS)
    result = run_holdout_seeds(recipe, data_dir=data_dir, seeds=3)

    assert len(result["per_seed"]) == 3, f"Expected 3 per_seed rows, got {len(result['per_seed'])}"
    for row in result["per_seed"]:
        assert "seed" in row, f"per_seed row missing 'seed' key: {row.keys()}"
        for k in ("ending_value", "sharpe", "psr", "max_drawdown"):
            assert math.isfinite(row[k]), f"per_seed metric {k} not finite: {row[k]}"
    # Seed values are distinct integers 1..N.
    assert [row["seed"] for row in result["per_seed"]] == [1, 2, 3]

    summary = result["summary"]
    assert set(summary.keys()) >= {"ending_value", "sharpe", "psr", "max_drawdown"}, f"summary keys: {summary.keys()}"
    for metric, stats in summary.items():
        for stat_key in ("mean", "std", "min", "max"):
            assert stat_key in stats, f"summary[{metric}] missing key {stat_key}"
            assert math.isfinite(stats[stat_key]), f"summary[{metric}][{stat_key}] not finite"

    # JSON round-trip (mirrors command.py writing holdout_seeds.json): all floats serialise cleanly.
    artifact_path = tmp_path / "holdout_seeds.json"
    artifact_path.write_text(json.dumps(result, indent=2))
    loaded = json.loads(artifact_path.read_text())
    assert len(loaded["per_seed"]) == 3
    assert set(loaded["summary"]) >= {"ending_value", "sharpe", "psr", "max_drawdown"}


def test_default_single_seed_no_holdout_seeds_artifact(tmp_path):
    """seeds=1 (default) writes no holdout_seeds.json — the default path is unchanged."""
    data_dir = tmp_path / "provider"
    shutil.copytree(PROVIDER, data_dir)
    out_dir = tmp_path / "out"

    recipe = dataclasses.replace(skeleton.RECIPE, segments=_FIXTURE_SEGMENTS)
    # Run via the direct API (mirrors what the CLI does for --seeds 1 --quick).
    run_experiment(recipe, data_dir=data_dir, out_dir=out_dir, refresh_cache=True)

    # The CLI writes holdout_seeds.json only when seeds > 1; the direct scaffold does not write it.
    # Assert no holdout_seeds.json anywhere under out_dir.
    artifacts = list(out_dir.rglob("holdout_seeds.json"))
    assert artifacts == [], f"Unexpected holdout_seeds.json at seeds=1: {artifacts}"


def test_determinism_reproduces_and_variance_is_real(tmp_path):
    """deterministic=True reproduces identical per-seed metrics; deterministic=False shows variance across seeds.

    Bit-repro guarantee: two successive run_holdout_seeds(seeds=1, deterministic=True) calls in
    the same process must yield sharpe within 1e-9 (exact float equality expected for LightGBM
    force_row_wise + deterministic=True on same machine; tolerance guards cross-machine float
    edge cases). Variance check: a 3-seed non-deterministic run must produce at least one pair of
    seeds with different sharpe (confirms seed variation actually shifts the booster).

    Note: intra-process repro is tested here. Cross-process repro can differ due to LightGBM
    thread-count detection at startup; that is out of scope for this fixture.

    The variance assertion (not all_same) is probabilistically safe for this fixture's ~120-day
    holdout — seed-to-seed bagging RNG differences virtually always shift the float sharpe — but
    is not a hard guarantee (extremely unlikely the three seeds produce identical floats).
    """
    from cli.experiment.multiseed import run_holdout_seeds

    data_dir = tmp_path / "provider"
    shutil.copytree(PROVIDER, data_dir)

    recipe = dataclasses.replace(skeleton.RECIPE, segments=_FIXTURE_SEGMENTS)

    # --- deterministic=True, seeds=1: two calls must produce the same sharpe (within 1e-9) ---
    run_a = run_holdout_seeds(recipe, data_dir=data_dir, seeds=1, deterministic=True)
    run_b = run_holdout_seeds(recipe, data_dir=data_dir, seeds=1, deterministic=True)
    sharpe_a = run_a["per_seed"][0]["sharpe"]
    sharpe_b = run_b["per_seed"][0]["sharpe"]
    assert abs(sharpe_a - sharpe_b) < 1e-9, f"deterministic=True did not reproduce: sharpe_a={sharpe_a:.9f} sharpe_b={sharpe_b:.9f}"

    # --- deterministic=False, seeds=3: at least two seeds must differ (variance is real) ---
    run_var = run_holdout_seeds(recipe, data_dir=data_dir, seeds=3, deterministic=False)
    sharpes = [row["sharpe"] for row in run_var["per_seed"]]
    all_same = len(set(sharpes)) == 1
    assert not all_same, f"Expected seed variance (different sharpes across 3 seeds) but all were identical: {sharpes}"
