from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
from typer.testing import CliRunner

from cli.__main__ import app

runner = CliRunner()


def _bundle(out, recipe, run, dates, rets):
    d = out / recipe / run
    d.mkdir(parents=True)
    pd.DataFrame({"date": dates, "ret": rets}).to_csv(d / "returns.csv", index=False)


def test_rank_two_trials(tmp_path):
    dates = pd.date_range("2025-01-01", periods=320, freq="D")
    rng = np.random.default_rng(0)
    _bundle(tmp_path, "skeleton", "20250101T000000Z", dates, rng.normal(0.002, 0.01, 320))
    _bundle(tmp_path, "variantb", "20250102T000000Z", dates, rng.normal(0.0, 0.01, 320))
    res = runner.invoke(app, ["rank", "--out", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert "2 trials" in res.output
    rj = json.loads((tmp_path / "rank.json").read_text())
    assert rj["n_trials"] == 2
    assert {"dsr_best", "pbo", "trials", "window"} <= set(rj)
    assert len(rj["trials"]) == 2
    assert all({"recipe", "run", "sharpe", "psr"} <= set(t) for t in rj["trials"])


def test_rank_no_trials_errors(tmp_path):
    res = runner.invoke(app, ["rank", "--out", str(tmp_path)])
    assert res.exit_code != 0
    assert "no trials" in res.output.lower()


def test_rank_single_trial_na(tmp_path):
    dates = pd.date_range("2025-01-01", periods=300, freq="D")
    _bundle(tmp_path, "only", "r1", dates, np.random.default_rng(1).normal(0.001, 0.01, 300))
    res = runner.invoke(app, ["rank", "--out", str(tmp_path)])
    assert res.exit_code == 0, res.output
    rj = json.loads((tmp_path / "rank.json").read_text())
    assert rj["n_trials"] == 1
    assert math.isnan(rj["dsr_best"]) and math.isnan(rj["pbo"])  # need >= 2 trials
