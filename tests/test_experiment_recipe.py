"""Tests for Recipe contract, skeleton recipe, and resolver."""

import dataclasses

import pytest

from cli.experiment.recipes.base import FEE_PRESETS, Recipe, resolve_recipe


def test_resolve_skeleton_name():
    recipe = resolve_recipe("skeleton")
    assert recipe.name == "skeleton"


def test_resolve_skeleton_universe_length():
    recipe = resolve_recipe("skeleton")
    assert len(recipe.universe) == 19


def test_resolve_skeleton_reference_instruments():
    recipe = resolve_recipe("skeleton")
    assert recipe.reference_instruments == ("BTCEUR", "ETHBTC")


def test_resolve_skeleton_account():
    recipe = resolve_recipe("skeleton")
    assert recipe.account == 10_000.0


def test_resolve_skeleton_benchmark():
    recipe = resolve_recipe("skeleton")
    assert recipe.benchmark == "BTCUSDT"


def test_resolve_skeleton_fee_preset():
    recipe = resolve_recipe("skeleton")
    assert recipe.fee_preset == "vip2_bnb"


def test_resolve_skeleton_segments():
    recipe = resolve_recipe("skeleton")
    assert set(recipe.segments) == {"train", "valid", "test"}


def test_fee_presets_vip2_bnb():
    assert FEE_PRESETS["vip2_bnb"] == (0.0006, 0.0006)


def test_resolve_unknown_recipe_raises_value_error():
    with pytest.raises(ValueError, match="skeleton"):
        resolve_recipe("does_not_exist")


def test_recipe_is_frozen():
    recipe = resolve_recipe("skeleton")
    with pytest.raises(dataclasses.FrozenInstanceError):
        recipe.name = "other"  # type: ignore[misc]
