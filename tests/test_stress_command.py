import dataclasses
import json
import shutil
from pathlib import Path

import pandas as pd
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


def _make_daily_series(n: int = 5) -> "pd.Series":
    """Return a tiny daily return Series with a DatetimeIndex."""
    import pandas as pd

    dates = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.Series([0.001] * n, index=dates)


def _fake_holdout(seen):
    # capture each window's (train, test) and return a fixed summary with sharpe + ls_sharpe.
    def _f(recipe, *, data_dir, seeds, deterministic=False):
        seen.append((recipe.segments["train"], recipe.segments["test"]))
        daily = _make_daily_series()
        return {
            "per_seed": [{"seed": 1, "sharpe": -0.5, "ls_sharpe": 0.4, "daily_long": daily, "daily_ls": daily}],
            "summary": {
                "sharpe": {"mean": -0.5, "std": 0.0, "min": -0.5, "max": -0.5, "n": 1},
                "ls_sharpe": {"mean": 0.4, "std": 0.0, "min": 0.4, "max": 0.4, "n": 1},
            },
        }

    return _f


def _patch(monkeypatch, tmp_path, seen):
    import cli.stress.command as cmd

    @dataclasses.dataclass
    class _Recipe:
        name: str = "steady"
        segments: dict = dataclasses.field(
            default_factory=lambda: {
                "train": ("2020-01-01", "2023-12-31"),
                "valid": ("2024-01-01", "2024-12-31"),
                "test": ("2025-01-01", "2026-06-15"),
            }
        )
        label_horizon_days: int = 6

    class _Idx:
        class calendar:
            from_date = "2020-01-01"
            to_date = "2026-06-19"  # the real calendar end; the command must leave a backtest tail buffer below it

    monkeypatch.setattr(cmd, "resolve_recipe", lambda name: _Recipe())
    monkeypatch.setattr(cmd, "load_config", lambda: {})
    monkeypatch.setattr(cmd, "resolve_data_dir", lambda d, cfg: tmp_path)
    monkeypatch.setattr(cmd, "load_index", lambda d: _Idx())
    monkeypatch.setattr(cmd, "run_holdout_seeds", _fake_holdout(seen))


def test_stress_loops_all_windows_and_writes_summary(monkeypatch, tmp_path):
    seen = []
    _patch(monkeypatch, tmp_path, seen)
    out = tmp_path / "runs"
    result = runner.invoke(app, ["stress", "--recipe", "steady", "--seeds", "1", "--null", "", "--out", str(out)])

    assert result.exit_code == 0, result.stdout
    # 4 OOS windows, each trained from 2020 only on prior data
    assert len(seen) == 4
    assert all(tr[0] == "2020-01-01" for tr, _te in seen)
    assert [te for _tr, te in seen] == [
        ("2022-01-01", "2022-12-31"),
        ("2023-01-01", "2023-12-31"),
        ("2024-01-01", "2024-12-31"),
        ("2025-01-01", "2026-06-17"),  # last window capped 2 days before the calendar end (qlib backtest tail buffer)
    ]
    # the last window's test_end must stay strictly below the calendar end (qlib peeks calendar[index+1])
    assert seen[-1][1][1] < "2026-06-19"
    # summary json written with one entry per window
    sj = sorted(out.glob("stress/steady/*/stress_summary.json"))
    assert sj, "stress_summary.json not written"
    data = json.loads(sj[-1].read_text())
    assert [w["label"] for w in data["windows"]] == ["oos_2022", "oos_2023", "oos_2024", "oos_2025"]
    assert data["windows"][0]["ls_sharpe_mean"] == 0.4
    # the per-window table is printed
    assert "oos_2022" in result.stdout and "ls_sharpe" in result.stdout.lower()


def test_stress_unknown_recipe_exits_nonzero(monkeypatch, tmp_path):
    import cli.stress.command as cmd

    def _raise(name):
        raise ValueError("Recipe 'nope' not found. Available: steady")

    monkeypatch.setattr(cmd, "resolve_recipe", _raise)
    result = runner.invoke(app, ["stress", "--recipe", "nope"])
    assert result.exit_code == 1


def test_stress_purge_scales_with_label_horizon(monkeypatch, tmp_path):
    import datetime as dt

    seen = []
    _patch(monkeypatch, tmp_path, seen)
    # override the patched recipe with a long-horizon one (label_horizon_days=20)
    import cli.stress.command as cmd

    @dataclasses.dataclass
    class _LongRecipe:
        name: str = "h20_steady"
        segments: dict = dataclasses.field(
            default_factory=lambda: {
                "train": ("2020-01-01", "2023-12-31"),
                "valid": ("2024-01-01", "2024-12-31"),
                "test": ("2025-01-01", "2026-06-15"),
            }
        )
        label_horizon_days: int = 20

    monkeypatch.setattr(cmd, "resolve_recipe", lambda name: _LongRecipe())
    out = tmp_path / "runs"
    result = runner.invoke(app, ["stress", "--recipe", "h20_steady", "--seeds", "1", "--null", "", "--out", str(out)])
    assert result.exit_code == 0, result.stdout
    # every window's train_end must be >= 20 days before its test_start (purge >= horizon)
    for train, test in seen:
        gap = (dt.date.fromisoformat(test[0]) - dt.date.fromisoformat(train[1])).days
        assert gap >= 20, f"purge {gap}d < label horizon 20d (leak)"


def test_stress_null_skip_when_empty(monkeypatch, tmp_path):
    """--null '' skips the null path; existing keys still present, no null/delta keys."""
    seen = []
    _patch(monkeypatch, tmp_path, seen)
    out = tmp_path / "runs"
    result = runner.invoke(app, ["stress", "--recipe", "steady", "--seeds", "1", "--null", "", "--out", str(out)])

    assert result.exit_code == 0, result.stdout
    sj = sorted(out.glob("stress/steady/*/stress_summary.json"))
    assert sj
    data = json.loads(sj[-1].read_text())
    w0 = data["windows"][0]
    # null keys absent when --null ""
    assert "null_sharpe_mean" not in w0
    assert "delta_sharpe" not in w0
    assert "delta_ci" not in w0
    assert "deflated_sharpe" not in data["aggregate"]
    assert "delta_mean_across_windows" not in data["aggregate"]


def test_stress_null_benchmarking_unit(monkeypatch, tmp_path):
    """With --null 'beta_null', per-window delta and CI are written; delta≈0 when cand==null."""
    seen = []
    _patch(monkeypatch, tmp_path, seen)
    out = tmp_path / "runs"
    result = runner.invoke(app, ["stress", "--recipe", "steady", "--seeds", "1", "--null", "beta_null", "--out", str(out)])

    assert result.exit_code == 0, result.stdout
    sj = sorted(out.glob("stress/steady/*/stress_summary.json"))
    assert sj
    data = json.loads(sj[-1].read_text())

    for w in data["windows"]:
        assert "null_sharpe_mean" in w
        assert "delta_sharpe" in w
        assert "delta_ci" in w
        assert set(w["delta_ci"].keys()) >= {"lo", "hi", "se"}
        # candidate == null (same fake_holdout), so delta ≈ 0
        assert abs(w["delta_sharpe"]) < 1e-6, f"expected delta≈0 but got {w['delta_sharpe']}"

    agg = data["aggregate"]
    assert "delta_mean_across_windows" in agg
    assert abs(agg["delta_mean_across_windows"]) < 1e-6
    assert "deflated_sharpe" in agg

    # trials.jsonl written at <out>/trials.jsonl
    trials_path = out / "trials.jsonl"
    assert trials_path.exists()
    lines = [json.loads(ln) for ln in trials_path.read_text().splitlines() if ln.strip()]
    assert len(lines) >= 1
    assert lines[-1]["recipe"] == "steady"

    # Registered sharpe must be per-period (non-annualized), matching deflated_sharpe's contract.
    # The fake holdout returns a daily series of [0.001]*5; per-period Sharpe of that pooled
    # series is 0.0 (zero std-dev with ddof=1 across identical values → degenerate → 0.0).
    # Regardless, it must NOT be the annualized mean-of-window-means (which would be ~-0.5,
    # the qlib annualized summary value the stub returns).
    from cli.experiment.stats import sharpe as _sharpe

    # Reconstruct the pooled daily series the command would have used (4 windows × 5 days).
    pooled = pd.concat([_make_daily_series() for _ in range(4)]).sort_index()
    expected_per_period_sharpe = _sharpe(pooled.to_numpy())
    registered_sharpe = lines[-1]["sharpe"]
    assert registered_sharpe == pytest.approx(expected_per_period_sharpe, abs=1e-9), (
        f"registered sharpe {registered_sharpe} != per-period sharpe {expected_per_period_sharpe}; "
        "unit-convention bug: annualized value was registered instead of per-period"
    )
    # Also confirm it is NOT the annualized mean-of-window-means (-0.5 from the stub).
    annualized_mean = -0.5  # the stub's summary["sharpe"]["mean"]
    assert abs(registered_sharpe - annualized_mean) > 0.1, (
        f"registered sharpe {registered_sharpe} suspiciously close to annualized mean {annualized_mean}; "
        "unit-convention bug: annualized value appears to have been registered"
    )


@pytest.mark.skipif(not _redis_up(), reason="needs redis (scripts/redis.sh start)")
def test_stress_null_benchmark_real_beta_null(tmp_path, monkeypatch):
    """Integration: stress --recipe beta_null --null beta_null -- delta_sharpe ≈ 0 every window.

    The embedded fixture spans 2023-01-02..2024-06-28, so _TEST_STARTS is patched to two
    windows that fit within that range and avoid the qlib backtest tail.
    """
    from importlib.resources import as_file, files

    import cli.stress.command as cmd

    # Two test windows within the fixture's 2023-01-02..2024-06-28 range.
    monkeypatch.setattr(cmd, "_TEST_STARTS", ["2023-06-01", "2024-01-01"])

    fixture_ref = files("cli.experiment").joinpath("data", "provider")
    data_dir = tmp_path / "provider"
    with as_file(fixture_ref) as src:
        shutil.copytree(src, data_dir)

    out = tmp_path / "runs"
    result = runner.invoke(
        app,
        [
            "stress",
            "--recipe",
            "beta_null",
            "--null",
            "beta_null",
            "--seeds",
            "2",
            "--data-dir",
            str(data_dir),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output

    sj = sorted(out.glob("stress/beta_null/*/stress_summary.json"))
    assert sj, "stress_summary.json not written"
    data = json.loads(sj[-1].read_text())

    for w in data["windows"]:
        assert "null_sharpe_mean" in w
        assert "delta_sharpe" in w
        assert "delta_ci" in w
        assert set(w["delta_ci"].keys()) >= {"lo", "hi", "se"}
        # candidate == null: same recipe, same seeds, deterministic — delta must be ≈ 0
        assert abs(w["delta_sharpe"]) < 1e-6, f"window {w['label']}: delta_sharpe={w['delta_sharpe']} not ≈ 0"

    agg = data["aggregate"]
    assert "delta_mean_across_windows" in agg
    assert abs(agg["delta_mean_across_windows"]) < 1e-6
    assert "deflated_sharpe" in agg

    # trials.jsonl written at <out>/trials.jsonl
    trials_path = out / "trials.jsonl"
    assert trials_path.exists(), "trials.jsonl not written"
    lines = [json.loads(ln) for ln in trials_path.read_text().splitlines() if ln.strip()]
    assert len(lines) >= 1
    assert lines[-1]["recipe"] == "beta_null"
