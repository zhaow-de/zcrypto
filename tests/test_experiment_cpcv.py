from __future__ import annotations

import dataclasses
import math
import shutil
from importlib.resources import as_file, files

import pytest


def test_lgb_params_default_has_no_seed_or_determinism():
    from cli.experiment.cpcv import _lgb_params
    from cli.experiment.recipes.base import resolve_recipe

    params, _ = _lgb_params(resolve_recipe("steady"))
    assert "seed" not in params and "deterministic" not in params and "force_row_wise" not in params


def test_lgb_params_injects_seed_and_determinism():
    from cli.experiment.cpcv import _lgb_params
    from cli.experiment.recipes.base import resolve_recipe

    params, _ = _lgb_params(resolve_recipe("steady"), seed=7, deterministic=True)
    assert params["seed"] == 7
    assert params["deterministic"] is True and params["force_row_wise"] is True


def test_lgb_params_seed_without_determinism():
    from cli.experiment.cpcv import _lgb_params
    from cli.experiment.recipes.base import resolve_recipe

    params, _ = _lgb_params(resolve_recipe("steady"), seed=3)
    assert params["seed"] == 3 and "deterministic" not in params


def test_seeded_model_config_injects_into_kwargs():
    from cli.experiment.scaffold import _seeded_model_config

    mc = {"class": "LGBModel", "module_path": "m", "kwargs": {"learning_rate": 0.03}}
    out = _seeded_model_config(mc, seed=5, deterministic=True)
    assert out["kwargs"]["seed"] == 5 and out["kwargs"]["deterministic"] is True and out["kwargs"]["force_row_wise"] is True
    assert mc["kwargs"] == {"learning_rate": 0.03}  # input not mutated
    assert _seeded_model_config(mc)["kwargs"] == {"learning_rate": 0.03}  # no-op default


def _redis_up() -> bool:
    try:
        import redis

        redis.Redis(host="localhost", port=6379, socket_connect_timeout=2).ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _redis_up(), reason="needs redis (scripts/redis.sh start)")
def test_run_cpcv_returns_distribution(tmp_path):
    from cli.experiment.cpcv import CPCVResult, run_cpcv
    from cli.experiment.recipes import skeleton

    fixture_ref = files("cli.experiment").joinpath("data", "provider")
    data_dir = tmp_path / "provider"
    with as_file(fixture_ref) as src:
        shutil.copytree(src, data_dir)

    # Scaled CV config that fits the fixture span (2023-01-02 .. 2024-06-28).
    recipe = dataclasses.replace(
        skeleton.RECIPE,
        segments={
            "train": ("2023-03-01", "2023-12-31"),
            "valid": ("2024-01-01", "2024-02-29"),
            "test": ("2024-03-01", "2024-06-27"),
        },
        feature_lookback_days=5,
        label_horizon_days=2,
        cv_n_groups=4,
        cv_test_groups=2,
    )

    result = run_cpcv(recipe, data_dir=data_dir, refresh_cache=True)

    assert isinstance(result, CPCVResult)
    assert result.meta["n_splits"] == 6  # C(4,2)
    assert result.meta["n_paths"] == 3  # C(3,1)
    assert len(result.paths) == 3
    for p in result.paths:
        assert {"path", "sharpe", "annualized_return", "max_drawdown"} <= set(p)
        assert isinstance(p["sharpe"], float)
        assert math.isfinite(p["sharpe"])
    assert {"sharpe_mean", "sharpe_std", "sharpe_median", "sharpe_worst"} <= set(result.distribution)
    assert {"mean", "std", "ir"} <= set(result.rank_ic)
    assert math.isfinite(result.distribution["sharpe_mean"])
    assert math.isfinite(result.rank_ic["mean"])
