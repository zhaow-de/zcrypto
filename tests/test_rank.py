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
    assert "*" in res.output  # best trial is marked
    rj = json.loads((tmp_path / "rank.json").read_text())
    assert rj["n_trials"] == 2
    assert {"dsr_best", "pbo", "trials", "window"} <= set(rj)
    assert len(rj["trials"]) == 2
    assert all({"recipe", "run", "sharpe_daily", "psr"} <= set(t) for t in rj["trials"])
    by_recipe = {t["recipe"]: t["sharpe_daily"] for t in rj["trials"]}
    assert by_recipe["skeleton"] > by_recipe["variantb"]  # higher-mean trial → higher daily Sharpe


def test_rank_warns_on_window_mismatch(tmp_path):
    rng = np.random.default_rng(0)
    a_dates = pd.date_range("2025-01-01", periods=300, freq="D")
    b_dates = pd.date_range("2025-09-01", periods=300, freq="D")  # only partial overlap with A
    _bundle(tmp_path, "skeleton", "20250101T000000Z", a_dates, rng.normal(0.001, 0.01, 300))
    _bundle(tmp_path, "variantb", "20250102T000000Z", b_dates, rng.normal(0.0, 0.01, 300))
    res = runner.invoke(app, ["rank", "--out", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert "differ materially" in res.output


def test_rank_disjoint_dates_errors(tmp_path):
    rng = np.random.default_rng(0)
    a_dates = pd.date_range("2025-01-01", periods=100, freq="D")
    b_dates = pd.date_range("2026-06-01", periods=100, freq="D")  # no overlap with A
    _bundle(tmp_path, "skeleton", "20250101T000000Z", a_dates, rng.normal(0.001, 0.01, 100))
    _bundle(tmp_path, "variantb", "20250102T000000Z", b_dates, rng.normal(0.0, 0.01, 100))
    res = runner.invoke(app, ["rank", "--out", str(tmp_path)])
    assert res.exit_code != 0
    assert "no common dates" in res.output.lower()


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


def _write_trials_jsonl(path, entries):
    """Write a trials.jsonl with the given list of (config_hash, sharpe) tuples."""
    import uuid

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for i, (config_hash, sr) in enumerate(entries):
            record = {
                "id": uuid.uuid4().hex,
                "recipe": f"recipe_{i}",
                "config_hash": config_hash,
                "sharpe": sr,
                "created": "2025-01-01T00:00:00Z",
            }
            fh.write(json.dumps(record) + "\n")


def test_rank_cumulative_register_lowers_dsr(tmp_path):
    """DSR with a register of extra trials must be <= DSR from in-run trials only."""
    from cli.experiment.stats import deflated_sharpe, sharpe

    dates = pd.date_range("2025-01-01", periods=320, freq="D")
    rng = np.random.default_rng(42)
    rets_a = rng.normal(0.002, 0.01, 320)
    rets_b = rng.normal(0.0, 0.01, 320)
    _bundle(tmp_path, "skeleton", "20250101T000000Z", dates, rets_a)
    _bundle(tmp_path, "variantb", "20250102T000000Z", dates, rets_b)

    # Seed a register with 5 extra trials with distinct config_hashes and varied Sharpes
    register_path = tmp_path / "trials.jsonl"
    extra_trials = [
        ("hash_extra_1", 0.08),
        ("hash_extra_2", 0.12),
        ("hash_extra_3", 0.05),
        ("hash_extra_4", -0.02),
        ("hash_extra_5", 0.15),
    ]
    _write_trials_jsonl(register_path, extra_trials)

    # Run rank without register (default: register absent → in-run only)
    res_no_reg = runner.invoke(app, ["rank", "--out", str(tmp_path), "--trials-register", str(tmp_path / "nonexistent.jsonl")])
    assert res_no_reg.exit_code == 0, res_no_reg.output
    rj_no_reg = json.loads((tmp_path / "rank.json").read_text())
    dsr_no_reg = rj_no_reg["dsr_best"]

    # Run rank with register
    res_with_reg = runner.invoke(app, ["rank", "--out", str(tmp_path), "--trials-register", str(register_path)])
    assert res_with_reg.exit_code == 0, res_with_reg.output
    rj_with_reg = json.loads((tmp_path / "rank.json").read_text())
    dsr_with_reg = rj_with_reg["dsr_best"]

    # More trials → higher expected-max Sharpe → lower or equal DSR
    assert dsr_with_reg <= dsr_no_reg, f"Expected DSR with register ({dsr_with_reg:.4f}) <= DSR without ({dsr_no_reg:.4f})"
    # The two values must differ (register entries actually affected the computation)
    assert dsr_with_reg != dsr_no_reg, "Register had no effect on DSR — check union/dedup logic"


def test_rank_absent_register_falls_back(tmp_path):
    """When --trials-register points to a non-existent file, rank completes normally."""
    dates = pd.date_range("2025-01-01", periods=320, freq="D")
    rng = np.random.default_rng(7)
    _bundle(tmp_path, "skeleton", "20250101T000000Z", dates, rng.normal(0.002, 0.01, 320))
    _bundle(tmp_path, "variantb", "20250102T000000Z", dates, rng.normal(0.0, 0.01, 320))
    res = runner.invoke(app, ["rank", "--out", str(tmp_path), "--trials-register", str(tmp_path / "no_such_file.jsonl")])
    assert res.exit_code == 0, res.output
    rj = json.loads((tmp_path / "rank.json").read_text())
    assert rj["n_trials"] == 2
    assert not math.isnan(rj["dsr_best"])
