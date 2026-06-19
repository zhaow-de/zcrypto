from __future__ import annotations

import dataclasses
import json
import shutil
from importlib.resources import as_file, files
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.__main__ import app

runner = CliRunner()


def _redis_up() -> bool:
    try:
        import redis

        redis.Redis(host="localhost", port=6379, socket_connect_timeout=2).ping()
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Fast, no redis/qlib needed.
# --------------------------------------------------------------------------
def test_unknown_recipe_exits_nonzero_and_lists_available():
    result = runner.invoke(app, ["experiment", "--recipe", "does_not_exist"])
    assert result.exit_code != 0
    assert "skeleton" in result.output


def test_experiment_help():
    result = runner.invoke(app, ["experiment", "--help"])
    assert result.exit_code == 0


def test_experiment_errors_when_no_data_dir_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no zcrypto.toml; no --data-dir flag
    result = runner.invoke(app, ["experiment", "--recipe", "skeleton"])
    assert result.exit_code != 0
    assert "no data_dir configured" in result.output


# --------------------------------------------------------------------------
# Fast wiring tests: monkeypatch heavy fns to capture kwargs.
# --------------------------------------------------------------------------
def _make_fake_result(tmp_path):
    """Build a minimal RunResult-alike that lets command.py run to completion."""
    import numpy as np
    import pandas as pd

    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    report_df = pd.DataFrame({"return": np.zeros(5), "cost": np.zeros(5), "bench": np.zeros(5)}, index=dates)
    return type(
        "RunResult",
        (),
        {
            "run_id": "fake-run-id",
            "ending_value": 10000.0,
            "report_df": report_df,
            "positions": {},
            "analysis_df": pd.DataFrame(),
            "account_curve": pd.Series(np.ones(5), index=dates),
            "benchmark_curve": pd.Series(np.ones(5), index=dates),
            "context_prices": {},
            "metrics": {
                "strategy_absolute": {"information_ratio": 0.5, "annualized_return": 0.1, "max_drawdown": -0.1},
                "excess_return_with_cost": {"annualized_return": 0.05, "max_drawdown": -0.05, "information_ratio": 0.3},
                "excess_return_without_cost": {},
            },
            "recorder_dir": tmp_path,
            "recipe": None,
            "data_fingerprint": "abc123",
            "wf_periods": None,
        },
    )()


def _patch_experiment_heavy_fns(monkeypatch, tmp_path, captured, fake_result):
    """Monkeypatch the deferred-import heavy functions and supporting helpers."""
    import cli.experiment.cpcv as cpcv_mod
    import cli.experiment.multiseed as multiseed_mod
    import cli.experiment.scaffold as scaffold_mod

    def fake_run_cpcv(recipe, *, data_dir, refresh_cache=False, seed=None, deterministic=False):
        captured["run_cpcv_kwargs"] = {"seed": seed, "deterministic": deterministic, "refresh_cache": refresh_cache}
        return type(
            "CPCVResult",
            (),
            {
                "meta": {"n_paths": 3},
                "paths": [{"sharpe": 0.5}],
                "distribution": {"sharpe_mean": 0.5, "sharpe_std": 0.1, "sharpe_worst": 0.2},
                "rank_ic": {"mean": 0.05},
            },
        )()

    def fake_run_experiment(recipe, *, data_dir, out_dir, refresh_cache=False, seed=None, deterministic=False):
        captured["run_experiment_kwargs"] = {"seed": seed, "deterministic": deterministic, "refresh_cache": refresh_cache}
        return fake_result

    def fake_run_holdout_seeds(recipe, *, data_dir, seeds, deterministic=False):
        captured["run_holdout_seeds_kwargs"] = {"seeds": seeds, "deterministic": deterministic}
        return {
            "per_seed": [
                {"seed": k, "ending_value": 10000.0, "sharpe": 0.5, "psr": 0.7, "max_drawdown": -0.1} for k in range(1, seeds + 1)
            ],
            "summary": {"ending_value": {"mean": 10000.0, "std": 0.0, "min": 10000.0, "max": 10000.0, "n": seeds}},
        }

    monkeypatch.setattr(cpcv_mod, "run_cpcv", fake_run_cpcv)
    monkeypatch.setattr(scaffold_mod, "run_experiment", fake_run_experiment)
    monkeypatch.setattr(multiseed_mod, "run_holdout_seeds", fake_run_holdout_seeds)

    # Also stub the report/chart helpers so no kaleido/plotly is needed.
    import cli.experiment.report as report_mod

    monkeypatch.setattr(report_mod, "build_report", lambda *a, **kw: object())
    monkeypatch.setattr(report_mod, "write_report", lambda *a, **kw: None)

    # Stub trades helpers.
    import cli.experiment.trades as trades_mod

    monkeypatch.setattr(
        trades_mod, "trades_from_positions", lambda positions: __import__("pandas").DataFrame({"side": [], "size": [], "price": []})
    )
    monkeypatch.setattr(trades_mod, "trade_summary", lambda trades: {"total": 0, "buys": 0, "sells": 0})


def test_experiment_passes_seeds_and_deterministic(monkeypatch, tmp_path):
    """--seeds 5 --deterministic wires through to run_experiment + run_holdout_seeds."""
    import dataclasses as dc

    from cli.experiment.recipes import skeleton

    short_recipe = dc.replace(
        skeleton.RECIPE,
        segments={
            "train": ("2023-03-01", "2023-12-31"),
            "valid": ("2024-01-01", "2024-02-29"),
            "test": ("2024-03-01", "2024-06-27"),
        },
    )
    monkeypatch.setattr("cli.experiment.command.resolve_recipe", lambda name: short_recipe)
    monkeypatch.setattr("cli.experiment.command.load_config", lambda: {})
    monkeypatch.setattr("cli.experiment.command.resolve_data_dir", lambda d, cfg: tmp_path)

    captured = {}
    fake_result = _make_fake_result(tmp_path)
    _patch_experiment_heavy_fns(monkeypatch, tmp_path, captured, fake_result)

    result = runner.invoke(
        app,
        [
            "experiment",
            "--recipe",
            "skeleton",
            "--data-dir",
            str(tmp_path),
            "--out",
            str(tmp_path / "runs"),
            "--no-open",
            "--quick",
            "--seeds",
            "5",
            "--deterministic",
        ],
    )
    assert result.exit_code == 0, result.output

    # run_experiment must receive seed=1, deterministic=True
    assert captured["run_experiment_kwargs"]["seed"] == 1
    assert captured["run_experiment_kwargs"]["deterministic"] is True

    # run_holdout_seeds must be called with seeds=5, deterministic=True
    assert "run_holdout_seeds_kwargs" in captured
    assert captured["run_holdout_seeds_kwargs"]["seeds"] == 5
    assert captured["run_holdout_seeds_kwargs"]["deterministic"] is True

    # holdout_seeds.json must be written inside the bundle
    bundles = list((tmp_path / "runs" / "skeleton").glob("*"))
    assert bundles, "no bundle directory created"
    bundle = bundles[0]
    assert (bundle / "holdout_seeds.json").exists()
    hs = json.loads((bundle / "holdout_seeds.json").read_text())
    assert "per_seed" in hs
    assert "summary" in hs
    assert len(hs["per_seed"]) == 5


def test_experiment_default_no_holdout_seeds(monkeypatch, tmp_path):
    """Default invocation (--seeds 1, no --deterministic) must NOT call run_holdout_seeds."""
    import dataclasses as dc

    from cli.experiment.recipes import skeleton

    short_recipe = dc.replace(
        skeleton.RECIPE,
        segments={
            "train": ("2023-03-01", "2023-12-31"),
            "valid": ("2024-01-01", "2024-02-29"),
            "test": ("2024-03-01", "2024-06-27"),
        },
    )
    monkeypatch.setattr("cli.experiment.command.resolve_recipe", lambda name: short_recipe)
    monkeypatch.setattr("cli.experiment.command.load_config", lambda: {})
    monkeypatch.setattr("cli.experiment.command.resolve_data_dir", lambda d, cfg: tmp_path)

    captured = {}
    fake_result = _make_fake_result(tmp_path)
    _patch_experiment_heavy_fns(monkeypatch, tmp_path, captured, fake_result)

    result = runner.invoke(
        app,
        [
            "experiment",
            "--recipe",
            "skeleton",
            "--data-dir",
            str(tmp_path),
            "--out",
            str(tmp_path / "runs"),
            "--no-open",
            "--quick",
        ],
    )
    assert result.exit_code == 0, result.output

    # Default: seed=None, deterministic=False
    assert captured["run_experiment_kwargs"]["seed"] is None
    assert captured["run_experiment_kwargs"]["deterministic"] is False

    # run_holdout_seeds must NOT be called
    assert "run_holdout_seeds_kwargs" not in captured

    # No holdout_seeds.json
    bundles = list((tmp_path / "runs" / "skeleton").glob("*"))
    assert bundles
    bundle = bundles[0]
    assert not (bundle / "holdout_seeds.json").exists()


# --------------------------------------------------------------------------
# End-to-end, redis-gated (~100s).
# --------------------------------------------------------------------------
@pytest.mark.skipif(not _redis_up(), reason="needs redis (scripts/redis.sh start)")
def test_experiment_end_to_end(tmp_path, monkeypatch):
    # Copy the committed fixture so caches/mlruns don't pollute the source tree.
    fixture_ref = files("cli.experiment").joinpath("data", "provider")
    data_dir = tmp_path / "provider"
    with as_file(fixture_ref) as src:
        shutil.copytree(src, data_dir)

    out_dir = tmp_path / "runs"

    # Patch resolve_recipe so the run uses SHORT segments that fit the fixture span.
    from cli.experiment.recipes import skeleton

    short_recipe = dataclasses.replace(
        skeleton.RECIPE,
        segments={
            "train": ("2023-03-01", "2023-12-31"),
            "valid": ("2024-01-01", "2024-02-29"),
            "test": ("2024-03-01", "2024-06-27"),
        },
    )
    monkeypatch.setattr("cli.experiment.command.resolve_recipe", lambda name: short_recipe)

    result = runner.invoke(
        app,
        [
            "experiment",
            "--recipe",
            "skeleton",
            "--data-dir",
            str(data_dir),
            "--out",
            str(out_dir),
            "--no-open",
            "--refresh-cache",
            "--quick",
        ],
    )
    assert result.exit_code == 0, result.output

    bundles = list((out_dir / "skeleton").glob("*"))
    assert len(bundles) == 1, bundles
    bundle = bundles[0]

    expected = [
        "report.html",
        "metrics.json",
        "trades.csv",
        "run_meta.json",
        "recipe_snapshot.json",
        "model.pkl",
    ]
    for name in expected:
        assert (bundle / name).exists(), f"missing {name} in {bundle}"

    assert "USDT" in result.output

    meta = json.loads((bundle / "run_meta.json").read_text())
    assert meta["index_fingerprint"]
    assert meta["run_id"]

    assert not (bundle / "cv_results.json").exists()  # --quick skips CPCV
    assert "CPCV" not in result.output


@pytest.mark.skipif(not _redis_up(), reason="needs redis (scripts/redis.sh start)")
def test_experiment_writes_returns_and_psr(tmp_path, monkeypatch):
    fixture_ref = files("cli.experiment").joinpath("data", "provider")
    data_dir = tmp_path / "provider"
    with as_file(fixture_ref) as src:
        shutil.copytree(src, data_dir)
    from cli.experiment.recipes import skeleton

    short = dataclasses.replace(
        skeleton.RECIPE,
        segments={
            "train": ("2023-03-01", "2023-12-31"),
            "valid": ("2024-01-01", "2024-02-29"),
            "test": ("2024-03-01", "2024-06-27"),
        },
    )
    monkeypatch.setattr("cli.experiment.command.resolve_recipe", lambda name: short)
    out_dir = tmp_path / "runs"
    result = runner.invoke(
        app,
        [
            "experiment",
            "--recipe",
            "skeleton",
            "--data-dir",
            str(data_dir),
            "--out",
            str(out_dir),
            "--no-open",
            "--refresh-cache",
            "--quick",
        ],
    )
    assert result.exit_code == 0, result.output
    bundle = next(iter((out_dir / "skeleton").glob("*")))
    assert (bundle / "returns.csv").exists()  # persisted in both modes
    assert "PSR" in result.output  # stdout PSR line


@pytest.mark.skipif(not _redis_up(), reason="needs redis (scripts/redis.sh start)")
def test_experiment_default_writes_cv_results(tmp_path, monkeypatch):
    fixture_ref = files("cli.experiment").joinpath("data", "provider")
    data_dir = tmp_path / "provider"
    with as_file(fixture_ref) as src:
        shutil.copytree(src, data_dir)
    from cli.experiment.recipes import skeleton

    short = dataclasses.replace(
        skeleton.RECIPE,
        segments={
            "train": ("2023-03-01", "2023-12-31"),
            "valid": ("2024-01-01", "2024-02-29"),
            "test": ("2024-03-01", "2024-06-27"),
        },
        feature_lookback_days=5,
        cv_n_groups=4,
        cv_test_groups=2,
    )
    monkeypatch.setattr("cli.experiment.command.resolve_recipe", lambda name: short)
    out_dir = tmp_path / "runs"
    result = runner.invoke(
        app,
        ["experiment", "--recipe", "skeleton", "--data-dir", str(data_dir), "--out", str(out_dir), "--no-open", "--refresh-cache"],
    )
    assert result.exit_code == 0, result.output
    bundle = next(iter((out_dir / "skeleton").glob("*")))
    cv = json.loads((bundle / "cv_results.json").read_text())
    assert cv["cv"]["n_paths"] == 3
    assert len(cv["paths"]) == 3
    assert "sharpe_mean" in cv["distribution"]
    assert "mean" in cv["rank_ic"]
    assert "sharpe" in cv["holdout"]
    assert "ending_value" in cv["holdout"]
    assert "psr" in cv["holdout"]
    assert "CPCV" in result.output


@pytest.mark.skipif(not _redis_up(), reason="needs redis (scripts/redis.sh start)")
def test_experiment_emits_survivorship_caveat(tmp_path, monkeypatch):
    fixture_ref = files("cli.experiment").joinpath("data", "provider")
    data_dir = tmp_path / "provider"
    with as_file(fixture_ref) as src:
        shutil.copytree(src, data_dir)
    from cli.experiment.recipes import skeleton

    short = dataclasses.replace(
        skeleton.RECIPE,
        segments={
            "train": ("2023-03-01", "2023-12-31"),
            "valid": ("2024-01-01", "2024-02-29"),
            "test": ("2024-03-01", "2024-06-27"),
        },
    )
    monkeypatch.setattr("cli.experiment.command.resolve_recipe", lambda name: short)
    out_dir = tmp_path / "runs"
    # --quick is enough: the caveat code path is run-mode-independent, and this keeps the test fast.
    result = runner.invoke(
        app,
        [
            "experiment",
            "--recipe",
            "skeleton",
            "--data-dir",
            str(data_dir),
            "--out",
            str(out_dir),
            "--no-open",
            "--refresh-cache",
            "--quick",
        ],
    )
    assert result.exit_code == 0, result.output
    bundle = next(iter((out_dir / "skeleton").glob("*")))
    meta = json.loads((bundle / "run_meta.json").read_text())
    assert "T0005" in {c["topic"] for c in meta["caveats"]}  # survivorship caveat recorded
    assert "survivorship" in result.output.lower()  # stdout caveat line printed
