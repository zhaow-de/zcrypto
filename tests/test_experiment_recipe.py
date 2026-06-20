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
            strategy_config={},
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
    assert resolve_recipe("steady").strategy_config["kwargs"] == {"topk": 10, "n_drop": 1, "hold_thresh": 5}


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


def test_strategy_config_with_signal_injects_signal():
    from cli.experiment.scaffold import strategy_config_with_signal

    cfg = {"class": "TopkDropoutStrategy", "module_path": "m", "kwargs": {"topk": 5}}
    out = strategy_config_with_signal(cfg, signal="SIG")
    assert out["class"] == "TopkDropoutStrategy" and out["module_path"] == "m"
    assert out["kwargs"] == {"topk": 5, "signal": "SIG"}
    assert cfg["kwargs"] == {"topk": 5}  # input not mutated


def test_skeleton_strategy_config_is_topk_dropout_unchanged():
    r = resolve_recipe("skeleton")
    sc = r.strategy_config
    assert sc["class"] == "TopkDropoutStrategy"
    assert sc["module_path"] == "qlib.contrib.strategy.signal_strategy"
    assert sc["kwargs"] == {"topk": 5, "n_drop": 1}


def test_steady_strategy_config_is_topk_dropout_unchanged():
    sc = resolve_recipe("steady").strategy_config
    assert sc["class"] == "TopkDropoutStrategy"
    assert sc["kwargs"] == {"topk": 10, "n_drop": 1, "hold_thresh": 5}


def test_recipe_walkforward_defaults_off():
    r = resolve_recipe("skeleton")
    assert r.wf_enabled is False
    assert r.wf_retrain_freq == "quarter"
    assert r.wf_window == "expanding"
    assert r.wf_rolling_years == 3


# --- regime_steady recipe: steady book + binary-200 regime overlay, walk-forward off for now ---


def test_regime_steady_uses_regime_strategy():
    r = resolve_recipe("regime_steady")
    sc = r.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["regime_mode"] == "binary"
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["vol_target"] is None  # default off
    # steady's book preserved
    assert sc["kwargs"]["topk"] == 10 and sc["kwargs"]["hold_thresh"] == 5


def test_regime_steady_matches_steady_book_and_label():
    rg, st = resolve_recipe("regime_steady"), resolve_recipe("steady")
    assert rg.universe == st.universe and rg.segments == st.segments
    assert rg.handler_kwargs["label"] == st.handler_kwargs["label"]
    assert rg.label_horizon_days == st.label_horizon_days == 6
    assert rg.wf_enabled is True  # Phase B: walk-forward holdout retraining enabled
    assert rg.wf_retrain_freq == "quarter"
    assert rg.wf_window == "expanding"


# --- feature_config seam: pluggable handler class (iter-13 Task 1) ---


def test_handler_config_builds_full_handler_dict():
    from cli.experiment.scaffold import handler_config

    out = handler_config(
        {"class": "Alpha158", "module_path": "qlib.contrib.data.handler"},
        instruments=["BTCUSDT", "ETHUSDT"],
        start="2020-01-01",
        end="2025-12-31",
        fit_start="2020-01-01",
        fit_end="2023-12-31",
        handler_kwargs={"label": (["x"], ["L"])},
    )
    assert out["class"] == "Alpha158" and out["module_path"] == "qlib.contrib.data.handler"
    assert out["kwargs"]["instruments"] == ["BTCUSDT", "ETHUSDT"]
    assert out["kwargs"]["start_time"] == "2020-01-01" and out["kwargs"]["end_time"] == "2025-12-31"
    assert out["kwargs"]["fit_start_time"] == "2020-01-01" and out["kwargs"]["fit_end_time"] == "2023-12-31"
    assert out["kwargs"]["freq"] == "day" and out["kwargs"]["label"] == (["x"], ["L"])


def test_benchmarks_use_alpha158_feature_config():
    for name in ("skeleton", "steady", "regime_steady"):
        fc = resolve_recipe(name).feature_config
        assert fc == {"class": "Alpha158", "module_path": "qlib.contrib.data.handler"}


# --- alpha360_steady recipe: steady book + Alpha360 features (A/B on feature handler) ---


def test_alpha360_steady_uses_alpha360_and_steady_book():
    r = resolve_recipe("alpha360_steady")
    assert r.feature_config == {"class": "Alpha360", "module_path": "qlib.contrib.data.handler"}
    st = resolve_recipe("steady")
    assert r.universe == st.universe and r.segments == st.segments
    assert r.strategy_config == st.strategy_config and r.model_config == st.model_config
    assert r.label_horizon_days == st.label_horizon_days


# --- crossasset_steady recipe: steady book + cross-asset features (A/B on feature information) ---


def test_crossasset_steady_prepends_cross_asset_processor():
    r = resolve_recipe("crossasset_steady")
    assert r.feature_config == {"class": "Alpha158", "module_path": "qlib.contrib.data.handler"}
    procs = r.handler_kwargs["infer_processors"]
    assert procs[0]["class"] == "CrossAssetProcessor"
    assert procs[0]["module_path"] == "cli.experiment.features.cross_asset"
    # steady's normalization still present, after the cross-asset step
    assert any(p["class"] == "RobustZScoreNorm" for p in procs)
    st = resolve_recipe("steady")
    assert r.universe == st.universe and r.model_config == st.model_config


# --- PIT universe additions (iter-18 Task 1) ---


def test_pit_additions_are_the_ten_delisted_faded_majors():
    from cli.experiment.recipes.base import PIT_ADDITIONS

    assert PIT_ADDITIONS == (
        "DASHUSDT",
        "ZECUSDT",
        "QTUMUSDT",
        "ICXUSDT",
        "FTTUSDT",
        "WAVESUSDT",
        "OMGUSDT",
        "XEMUSDT",
        "BTGUSDT",
        "NANOUSDT",
    )
    # LUNCUSDT is appended at closeout, not in the coded constant
    assert "LUNCUSDT" not in PIT_ADDITIONS


def test_with_pit_universe_appends_additions_order_preserving():
    from cli.experiment.recipes.base import PIT_ADDITIONS, resolve_recipe, with_pit_universe

    base = resolve_recipe("steady")
    pit = with_pit_universe(base)

    # frozen original untouched
    assert "NANOUSDT" not in base.universe
    # survivors kept first, in order; additions appended
    assert pit.universe[: len(base.universe)] == base.universe
    assert pit.universe[len(base.universe) :] == PIT_ADDITIONS
    # only the universe changed
    import dataclasses

    assert dataclasses.replace(pit, universe=base.universe) == base


def test_with_pit_universe_dedups_overlap():
    import dataclasses

    from cli.experiment.recipes.base import resolve_recipe, with_pit_universe

    base = dataclasses.replace(resolve_recipe("steady"), universe=resolve_recipe("steady").universe + ("NANOUSDT",))
    pit = with_pit_universe(base)
    assert pit.universe.count("NANOUSDT") == 1
    assert len(pit.universe) == len(set(pit.universe))
