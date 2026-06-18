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


def test_recipe_has_cv_defaults():
    from cli.experiment.recipes import skeleton
    from cli.experiment.recipes.base import Recipe

    r = skeleton.RECIPE
    assert r.label_horizon_days == 2
    assert r.feature_lookback_days == 60
    assert r.cv_n_groups == 6
    assert r.cv_test_groups == 2
    # configurable
    assert (
        Recipe(
            name="x",
            handler_kwargs={},
            model_config={},
            strategy_kwargs={},
            segments={},
            universe=(),
            reference_instruments=(),
            cv_n_groups=4,
            cv_test_groups=2,
        ).cv_n_groups
        == 4
    )


# --- steady recipe: low-turnover, longer-horizon, regularized; risk-adjusted A/B vs skeleton ---


def test_resolve_steady_name():
    assert resolve_recipe("steady").name == "steady"


def test_steady_low_turnover_strategy():
    # Lever 2: diversified, sticky book to cut the 12 bps turnover drag.
    assert resolve_recipe("steady").strategy_kwargs == {"topk": 10, "n_drop": 1, "hold_thresh": 5}


def test_steady_label_horizon_matches_label():
    # Leak-safety invariant: the CPCV purge (label_horizon_days) must cover the
    # label's max forward Ref. steady's 5-day label -> Ref($close, -6) -> horizon 6.
    import re

    r = resolve_recipe("steady")
    label_exprs = r.handler_kwargs["label"][0]
    max_fwd = max(int(n) for expr in label_exprs for n in re.findall(r"Ref\(\$close,\s*-(\d+)\)", expr))
    assert max_fwd == r.label_horizon_days == 6


def test_steady_matches_skeleton_ab_controls():
    # Clean A/B: data-universe, segments, and fees identical to skeleton so the
    # comparison isolates the label / book / model changes.
    s, k = resolve_recipe("steady"), resolve_recipe("skeleton")
    assert s.universe == k.universe
    assert s.segments == k.segments
    assert s.fee_preset == k.fee_preset
    assert s.account == k.account
    assert s.benchmark == k.benchmark
    assert s.reference_instruments == k.reference_instruments
    # CV controls identical too (only label_horizon_days differs, by design: 6 vs 2).
    assert s.feature_lookback_days == k.feature_lookback_days
    assert s.cv_n_groups == k.cv_n_groups
    assert s.cv_test_groups == k.cv_test_groups


def test_steady_model_more_regularized_than_skeleton():
    # Lever 3: a simpler model generalizes better out-of-sample (what CPCV/PBO reward).
    s = resolve_recipe("steady").model_config["kwargs"]
    k = resolve_recipe("skeleton").model_config["kwargs"]
    assert s["learning_rate"] < k["learning_rate"]
    assert s["max_depth"] < k["max_depth"]
    assert s["num_leaves"] < k["num_leaves"]
    assert s["lambda_l1"] >= k["lambda_l1"]
    assert s["lambda_l2"] >= k["lambda_l2"]
    # lower row/column subsampling = more bagging regularization
    assert s["colsample_bytree"] < k["colsample_bytree"]
    assert s["subsample"] < k["subsample"]
