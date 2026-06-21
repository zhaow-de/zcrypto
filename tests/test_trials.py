"""Tests for cli/experiment/trials.py — pre-registered trial register + config hash."""

from __future__ import annotations

import json
import uuid

import numpy as np
import pytest

from cli.experiment.recipes.base import resolve_recipe
from cli.experiment.stats import deflated_sharpe
from cli.experiment.trials import cumulative_sr_trials, recipe_config_hash, register_trial

_CREATED = "2026-06-21T00:00:00Z"


# ---------------------------------------------------------------------------
# recipe_config_hash
# ---------------------------------------------------------------------------


def test_recipe_config_hash_stable():
    """Same recipe → same hash across two calls."""
    r = resolve_recipe("steady")
    assert recipe_config_hash(r) == recipe_config_hash(r)


def test_recipe_config_hash_differs_across_recipes():
    """Different recipes → different hashes."""
    h_steady = recipe_config_hash(resolve_recipe("steady"))
    h_skeleton = recipe_config_hash(resolve_recipe("skeleton"))
    assert h_steady != h_skeleton


def test_recipe_config_hash_is_hex_string():
    h = recipe_config_hash(resolve_recipe("steady"))
    assert isinstance(h, str)
    assert len(h) == 64  # sha256 hex
    int(h, 16)  # must be valid hex


# ---------------------------------------------------------------------------
# register_trial / cumulative_sr_trials
# ---------------------------------------------------------------------------


def test_missing_file_returns_empty(tmp_path):
    assert cumulative_sr_trials(tmp_path / "nonexistent.jsonl") == []


def test_dedup_last_wins(tmp_path):
    """Two trials sharing a config_hash: dedup keeps the LAST sharpe."""
    p = tmp_path / "trials.jsonl"
    shared_hash = "aabbcc"

    register_trial(p, recipe_name="steady", config_hash=shared_hash, sharpe=1.0, created=_CREATED)
    register_trial(p, recipe_name="steady", config_hash=shared_hash, sharpe=2.0, created=_CREATED)
    register_trial(p, recipe_name="skeleton", config_hash="ddeeff", sharpe=0.5, created=_CREATED)

    result = cumulative_sr_trials(p)
    assert len(result) == 2
    # shared_hash last-written sharpe is 2.0; unique hash 0.5
    assert set(result) == {2.0, 0.5}


def test_round_trip_keys(tmp_path):
    """Appended jsonl lines contain expected keys and are valid json."""
    p = tmp_path / "trials.jsonl"
    register_trial(p, recipe_name="steady", config_hash="abc123", sharpe=1.23, created=_CREATED)

    line = p.read_text(encoding="utf-8").strip()
    obj = json.loads(line)
    for key in ("id", "recipe", "config_hash", "sharpe", "created"):
        assert key in obj, f"missing key: {key}"
    assert obj["recipe"] == "steady"
    assert obj["config_hash"] == "abc123"
    assert obj["sharpe"] == pytest.approx(1.23)
    assert obj["created"] == _CREATED


def test_register_creates_parent_dirs(tmp_path):
    """register_trial creates parent directories if they do not exist."""
    p = tmp_path / "nested" / "deep" / "trials.jsonl"
    register_trial(p, recipe_name="steady", config_hash="x", sharpe=0.0, created=_CREATED)
    assert p.exists()


def test_cumulative_sr_trials_order_stable(tmp_path):
    """Order is stable (first-seen config_hash order)."""
    p = tmp_path / "trials.jsonl"
    register_trial(p, recipe_name="steady", config_hash="h1", sharpe=1.0, created=_CREATED)
    register_trial(p, recipe_name="steady", config_hash="h2", sharpe=2.0, created=_CREATED)
    register_trial(p, recipe_name="steady", config_hash="h1", sharpe=9.0, created=_CREATED)  # update h1

    result = cumulative_sr_trials(p)
    # h1 first-seen first, h2 second; values are last-seen
    assert result == [9.0, 2.0]


def test_deflated_sharpe_integration(tmp_path):
    """Feeding cumulative_sr_trials into deflated_sharpe runs without error."""
    p = tmp_path / "trials.jsonl"
    register_trial(p, recipe_name="steady", config_hash="h1", sharpe=0.8, created=_CREATED)
    register_trial(p, recipe_name="skeleton", config_hash="h2", sharpe=1.2, created=_CREATED)

    sr_trials = cumulative_sr_trials(p)
    rng = np.random.default_rng(0)
    returns = rng.normal(0.001, 0.02, 252)
    result = deflated_sharpe(returns, sr_trials)
    assert isinstance(result, float)


def test_id_field_is_unique(tmp_path):
    """Each registered trial gets a unique id."""
    p = tmp_path / "trials.jsonl"
    for i in range(5):
        register_trial(p, recipe_name="steady", config_hash=f"h{i}", sharpe=float(i), created=_CREATED)

    ids = [json.loads(line)["id"] for line in p.read_text(encoding="utf-8").strip().splitlines()]
    assert len(set(ids)) == 5
