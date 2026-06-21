import dataclasses
import json
from pathlib import Path

from typer.testing import CliRunner

from cli.__main__ import app

runner = CliRunner()


def _fake_holdout(seen):
    # capture each window's (train, test) and return a fixed summary with sharpe + ls_sharpe.
    def _f(recipe, *, data_dir, seeds, deterministic=False):
        seen.append((recipe.segments["train"], recipe.segments["test"]))
        return {
            "per_seed": [{"seed": 1, "sharpe": -0.5, "ls_sharpe": 0.4}],
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
    result = runner.invoke(app, ["stress", "--recipe", "steady", "--seeds", "1", "--out", str(out)])

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
    result = runner.invoke(app, ["stress", "--recipe", "h20_steady", "--seeds", "1", "--out", str(out)])
    assert result.exit_code == 0, result.stdout
    # every window's train_end must be >= 20 days before its test_start (purge >= horizon)
    for train, test in seen:
        gap = (dt.date.fromisoformat(test[0]) - dt.date.fromisoformat(train[1])).days
        assert gap >= 20, f"purge {gap}d < label horizon 20d (leak)"
