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
    assert "00005" in {c["topic"] for c in meta["caveats"]}  # survivorship caveat recorded
    assert "survivorship" in result.output.lower()  # stdout caveat line printed
