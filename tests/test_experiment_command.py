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
