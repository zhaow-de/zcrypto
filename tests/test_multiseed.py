from __future__ import annotations

import dataclasses
import shutil
from importlib.resources import as_file, files

import pytest

from cli.experiment.multiseed import separation, summarize_seed_metrics


def _redis_up() -> bool:
    try:
        import redis

        redis.Redis(host="localhost", port=6379, socket_connect_timeout=2).ping()
        return True
    except Exception:
        return False


def _fake_recipe():
    # run_holdout_seeds only threads `recipe` through to the monkeypatched seams,
    # so a bare sentinel is enough for the loop+aggregation unit.
    return object()


def _per_seed(vals):  # vals: list of sharpe values; fill others trivially
    return [{"ending_value": 10000 * (1 + v), "sharpe": v, "psr": 0.5, "max_drawdown": -0.5} for v in vals]


def test_summarize_basic_stats():
    s = summarize_seed_metrics(_per_seed([0.0, 0.2, 0.4]))
    assert s["sharpe"]["n"] == 3
    assert abs(s["sharpe"]["mean"] - 0.2) < 1e-9
    assert s["sharpe"]["min"] == 0.0 and s["sharpe"]["max"] == 0.4
    assert s["sharpe"]["std"] > 0


def test_separation_z():
    a = summarize_seed_metrics(_per_seed([0.5, 0.5, 0.5]))  # crossasset-like, tight
    b = summarize_seed_metrics(_per_seed([0.0, 0.0, 0.0]))  # steady-like, tight
    sep = separation(a, b, metric="sharpe")
    assert abs(sep["mean_gap"] - 0.5) < 1e-9
    assert sep["z"] > 0  # a separated above b


def test_separation_within_noise():
    a = summarize_seed_metrics(_per_seed([0.0, 0.3, -0.3, 0.4, -0.4]))
    b = summarize_seed_metrics(_per_seed([0.05, 0.25, -0.25, 0.35, -0.35]))
    sep = separation(a, b, metric="sharpe")
    assert abs(sep["z"]) < 1.0  # overlapping distributions -> not separated


def test_summarize_single_seed_std_zero():
    s = summarize_seed_metrics(_per_seed([0.3]))
    assert s["sharpe"]["n"] == 1
    assert s["sharpe"]["std"] == 0.0
    assert s["sharpe"]["mean"] == 0.3
    assert s["sharpe"]["min"] == 0.3
    assert s["sharpe"]["max"] == 0.3


def test_separation_divide_by_zero_nonzero_gap():
    # Both distributions have std==0 (single seed or identical values) but different means
    # pooled_std = 0, mean_gap != 0 -> z = inf
    a = summarize_seed_metrics(_per_seed([0.5]))
    b = summarize_seed_metrics(_per_seed([0.0]))
    sep = separation(a, b, metric="sharpe")
    assert sep["pooled_std"] == 0.0
    assert sep["z"] == float("inf")
    assert sep["mean_gap"] == 0.5


def test_separation_divide_by_zero_zero_gap():
    # Both distributions identical (std==0, gap==0) -> z = 0.0
    a = summarize_seed_metrics(_per_seed([0.3]))
    b = summarize_seed_metrics(_per_seed([0.3]))
    sep = separation(a, b, metric="sharpe")
    assert sep["pooled_std"] == 0.0
    assert sep["z"] == 0.0
    assert sep["mean_gap"] == 0.0


def test_holdout_metrics_includes_long_short(monkeypatch):
    import pandas as pd

    import cli.experiment.multiseed as ms

    # Synthetic holdout: 2 dates × 4 instruments; report_df is the long-only daily report.
    dates = pd.to_datetime(["2025-01-01", "2025-01-02"])
    insts = ["A", "B", "C", "D"]
    idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
    signal = pd.Series([4, 3, 2, 1, 4, 3, 2, 1], index=idx, dtype=float)  # A>B>C>D each day
    fwd = pd.Series([0.05, 0.0, 0.0, -0.05] * 2, index=idx, dtype=float)  # A up, D down
    report_df = pd.DataFrame({"return": [0.01, 0.01], "cost": [0.0, 0.0]}, index=dates)

    monkeypatch.setattr(ms, "_light_holdout", lambda recipe, *, seed, deterministic, ctx: (report_df, signal))

    class _Recipe:
        account = 10_000.0
        fee_preset = "vip2_bnb"
        fees_only = False
        maker_fill_haircut = 0.0

    class _Ctx:
        fwd_ret = fwd

    out = ms._holdout_metrics_for_seed(_Recipe(), 1, False, _Ctx())
    # long-only keys still present
    assert {"ending_value", "sharpe", "psr", "max_drawdown"} <= set(out)
    # new L/S keys present; k=1 leg → long A (0.05), short D (-0.05) → +0.10/day, positive
    assert "ls_sharpe" in out and "ls_ending" in out
    assert out["ls_ending"] > 1.0


def test_run_holdout_seeds_aggregates(monkeypatch):
    from cli.experiment import multiseed as ms

    # Stub the per-seed metric producer + the one-time qlib context so no qlib/redis is needed.
    monkeypatch.setattr(
        ms,
        "_holdout_metrics_for_seed",
        lambda recipe, seed, deterministic, ctx: {
            "ending_value": 10000 + seed,
            "sharpe": 0.1 * seed,
            "psr": 0.3,
            "max_drawdown": -0.4,
        },
    )
    monkeypatch.setattr(ms, "_holdout_context", lambda recipe, data_dir, deterministic: object())
    out = ms.run_holdout_seeds(_fake_recipe(), data_dir="x", seeds=4)
    assert len(out["per_seed"]) == 4
    assert [d["seed"] for d in out["per_seed"]] == [1, 2, 3, 4]
    assert out["summary"]["sharpe"]["n"] == 4
    assert abs(out["summary"]["sharpe"]["mean"] - 0.25) < 1e-9


def test_summarize_seed_metrics_sanitizes_nonfinite():
    """A fully gated-to-cash window yields a constant return series -> nan/inf Sharpe; the
    aggregation must map non-finite values to 0.0 instead of crashing statistics.stdev."""
    from cli.experiment.multiseed import summarize_seed_metrics

    per_seed = [
        {"sharpe": float("nan"), "ending": 10000.0},
        {"sharpe": float("inf"), "ending": 10000.0},
        {"sharpe": 0.0, "ending": 10000.0},
    ]
    out = summarize_seed_metrics(per_seed)
    assert out["sharpe"]["mean"] == 0.0  # all three sanitized/zero -> 0.0
    assert out["sharpe"]["std"] == 0.0
    assert out["ending"]["mean"] == 10000.0


def test_fit_predict_lgbm_branch_returns_predictions():
    """LGBM recipe -> the existing lgb path; returns one prediction per holdout row."""
    import numpy as np
    import pandas as pd

    from cli.experiment.multiseed import _fit_predict
    from cli.experiment.recipes.base import resolve_recipe

    rng = np.random.RandomState(0)
    x_tr = pd.DataFrame(rng.rand(60, 6))
    y_tr = pd.Series(rng.rand(60))
    x_pe = pd.DataFrame(rng.rand(9, 6))
    pred = _fit_predict(resolve_recipe("steady"), x_tr, y_tr, x_pe, seed=1, deterministic=True)
    assert len(pred) == 9


def test_fit_predict_generic_sklearn_branch_returns_predictions():
    """A non-LGBM (sklearn-style) model_config -> importlib + fit/predict on matrices."""
    from types import SimpleNamespace

    import numpy as np
    import pandas as pd

    from cli.experiment.multiseed import _fit_predict

    rng = np.random.RandomState(0)
    x_tr = pd.DataFrame(rng.rand(60, 6))
    y_tr = pd.Series(rng.rand(60))
    x_pe = pd.DataFrame(rng.rand(9, 6))
    recipe = SimpleNamespace(model_config={"class": "Ridge", "module_path": "sklearn.linear_model", "kwargs": {"alpha": 1.0}})
    pred = _fit_predict(recipe, x_tr, y_tr, x_pe, seed=1, deterministic=True)
    assert len(pred) == 9
    assert np.isfinite(pred).all()


@pytest.mark.skipif(not _redis_up(), reason="needs redis (scripts/redis.sh start)")
def test_run_holdout_seeds_daily_series(tmp_path):
    """run_holdout_seeds surfaces per-seed daily return Series and summary stays scalar-only."""
    import pandas as pd

    from cli.experiment.multiseed import run_holdout_seeds
    from cli.experiment.recipes import skeleton

    fixture_ref = files("cli.experiment").joinpath("data", "provider")
    data_dir = tmp_path / "provider"
    with as_file(fixture_ref) as src:
        shutil.copytree(src, data_dir)

    recipe = dataclasses.replace(
        skeleton.RECIPE,
        segments={
            "train": ("2023-03-01", "2023-12-31"),
            "valid": ("2024-01-01", "2024-02-29"),
            "test": ("2024-03-01", "2024-06-27"),
        },
    )

    res = run_holdout_seeds(recipe, data_dir=data_dir, seeds=2, deterministic=True)

    # per_seed entries carry both daily Series
    for entry in res["per_seed"]:
        assert isinstance(entry["daily_long"], pd.Series), "daily_long must be a pandas Series"
        assert len(entry["daily_long"]) > 0, "daily_long must be non-empty"
        assert isinstance(entry["daily_ls"], pd.Series), "daily_ls must be a pandas Series"
        assert len(entry["daily_ls"]) > 0, "daily_ls must be non-empty"

    # summary contains the existing scalar metric keys
    scalar_keys = {"sharpe", "ls_sharpe", "psr", "max_drawdown", "ending_value", "ls_ending"}
    assert scalar_keys <= set(res["summary"]), f"missing scalar keys in summary: {scalar_keys - set(res['summary'])}"
    for key in scalar_keys:
        assert set(res["summary"][key].keys()) == {"mean", "std", "min", "max", "n"}

    # summary does NOT contain the daily Series keys
    assert "daily_long" not in res["summary"], "summary must not contain daily_long"
    assert "daily_ls" not in res["summary"], "summary must not contain daily_ls"
