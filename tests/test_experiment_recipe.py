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


def test_pit_additions_are_the_eleven_delisted_faded_majors():
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
        "LUNCUSDT",
    )
    # LUNCUSDT is the Terra blow-up (old LUNA capped before Luna 2.0, renamed to Luna Classic).
    assert "LUNCUSDT" in PIT_ADDITIONS


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


def test_recipe_cost_fields_default_to_calibration():
    from cli.experiment.costs import COST_CALIBRATION
    from cli.experiment.recipes.base import resolve_recipe

    r = resolve_recipe("steady")
    assert r.impact_cost == COST_CALIBRATION["impact_cost"]
    assert r.maker_fill_haircut == COST_CALIBRATION["maker_fill_haircut"]
    assert r.fees_only is False


def _infer_classes(recipe):
    return [p["class"] for p in recipe.handler_kwargs["infer_processors"]]


def test_funding_steady_wires_processor_and_matches_steady_book():
    import dataclasses

    from cli.experiment.recipes.base import resolve_recipe

    fs = resolve_recipe("funding_steady")
    steady = resolve_recipe("steady")
    # FundingRateProcessor is prepended first, before RobustZScoreNorm.
    assert _infer_classes(fs)[0] == "FundingRateProcessor"
    assert _infer_classes(fs)[1] == "RobustZScoreNorm"
    # Book matches steady except name + infer_processors (clean A/B isolation).
    assert dataclasses.replace(fs, name="steady", handler_kwargs=steady.handler_kwargs) == steady


def test_funding_crossasset_steady_stacks_both_processors():
    import dataclasses

    from cli.experiment.recipes.base import resolve_recipe

    fx = resolve_recipe("funding_crossasset_steady")
    base = resolve_recipe("crossasset_steady")
    classes = _infer_classes(fx)
    # Both feature processors precede the normalizer.
    assert classes[:2] == ["CrossAssetProcessor", "FundingRateProcessor"]
    assert classes[2] == "RobustZScoreNorm"
    assert dataclasses.replace(fx, name="crossasset_steady", handler_kwargs=base.handler_kwargs) == base


# --- regime_fast recipe: steady book + faster binary-100 regime overlay (iter-23 responsiveness sweep) ---


def test_regime_fast_is_binary_100d_gate_on_steady_book():
    rf, st = resolve_recipe("regime_fast"), resolve_recipe("steady")
    sc = rf.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["regime_mode"] == "binary"
    assert sc["kwargs"]["regime_ma_window"] == 100  # faster than regime_steady's 200
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert sc["kwargs"]["vol_target"] is None
    assert sc["kwargs"]["topk"] == 10 and sc["kwargs"]["n_drop"] == 1 and sc["kwargs"]["hold_thresh"] == 5
    # steady's book preserved (clean A/B; the gate is the only change)
    assert rf.universe == st.universe and rf.segments == st.segments
    assert rf.handler_kwargs["label"] == st.handler_kwargs["label"]
    assert rf.model_config["kwargs"] == st.model_config["kwargs"]
    assert rf.feature_config == st.feature_config
    assert rf.fee_preset == st.fee_preset and rf.label_horizon_days == st.label_horizon_days


def test_regime_cross_is_50_200_cross_gate_on_steady_book():
    rc, st = resolve_recipe("regime_cross"), resolve_recipe("steady")
    sc = rc.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["regime_mode"] == "cross"
    assert sc["kwargs"]["regime_ma_fast"] == 50
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert sc["kwargs"]["vol_target"] is None
    assert sc["kwargs"]["topk"] == 10 and sc["kwargs"]["n_drop"] == 1 and sc["kwargs"]["hold_thresh"] == 5
    # steady's book preserved
    assert rc.universe == st.universe and rc.segments == st.segments
    assert rc.handler_kwargs["label"] == st.handler_kwargs["label"]
    assert rc.model_config["kwargs"] == st.model_config["kwargs"]
    assert rc.feature_config == st.feature_config
    assert rc.fee_preset == st.fee_preset and rc.label_horizon_days == st.label_horizon_days


# --- regime_graded recipe: steady book + graded 200-day regime gate (iter-24 refinement) ---


def test_regime_graded_is_graded_200d_band_on_steady_book():
    rg, st = resolve_recipe("regime_graded"), resolve_recipe("steady")
    sc = rg.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["regime_mode"] == "graded"
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["regime_band"] == 0.05
    assert sc["kwargs"]["chop_exposure"] == 0.5
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert sc["kwargs"]["vol_target"] is None
    assert sc["kwargs"]["topk"] == 10 and sc["kwargs"]["n_drop"] == 1 and sc["kwargs"]["hold_thresh"] == 5
    # steady's book preserved
    assert rg.universe == st.universe and rg.segments == st.segments
    assert rg.handler_kwargs["label"] == st.handler_kwargs["label"]
    assert rg.model_config["kwargs"] == st.model_config["kwargs"]
    assert rg.feature_config == st.feature_config
    assert rg.fee_preset == st.fee_preset and rg.label_horizon_days == st.label_horizon_days


def test_regime_voltarget_is_binary_200d_voltarget_on_steady_book():
    rv, st = resolve_recipe("regime_voltarget"), resolve_recipe("steady")
    sc = rv.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["regime_mode"] == "binary"
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["vol_target"] == 0.50
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert sc["kwargs"]["topk"] == 10 and sc["kwargs"]["n_drop"] == 1 and sc["kwargs"]["hold_thresh"] == 5
    # steady's book preserved
    assert rv.universe == st.universe and rv.segments == st.segments
    assert rv.handler_kwargs["label"] == st.handler_kwargs["label"]
    assert rv.model_config["kwargs"] == st.model_config["kwargs"]
    assert rv.feature_config == st.feature_config
    assert rv.fee_preset == st.fee_preset and rv.label_horizon_days == st.label_horizon_days


def test_regime_funding_voltarget_is_funding_book_plus_voltarget_gate():
    rf, fs = resolve_recipe("regime_funding_voltarget"), resolve_recipe("funding_steady")
    sc = rf.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["regime_mode"] == "binary"
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["vol_target"] == 0.50
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert sc["kwargs"]["topk"] == 10 and sc["kwargs"]["n_drop"] == 1 and sc["kwargs"]["hold_thresh"] == 5
    # funding_steady's book preserved (the FundingRateProcessor must stay FIRST in infer_processors)
    assert rf.handler_kwargs["infer_processors"] == fs.handler_kwargs["infer_processors"]
    assert rf.handler_kwargs["infer_processors"][0]["class"] == "FundingRateProcessor"
    assert rf.universe == fs.universe and rf.segments == fs.segments
    assert rf.handler_kwargs["label"] == fs.handler_kwargs["label"]
    assert rf.model_config["kwargs"] == fs.model_config["kwargs"]
    assert rf.feature_config == fs.feature_config
    assert rf.fee_preset == fs.fee_preset and rf.label_horizon_days == fs.label_horizon_days


def test_regime_crossasset_voltarget_is_crossasset_book_plus_voltarget_gate():
    rc, cs = resolve_recipe("regime_crossasset_voltarget"), resolve_recipe("crossasset_steady")
    sc = rc.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["regime_mode"] == "binary"
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["vol_target"] == 0.50
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert sc["kwargs"]["topk"] == 10 and sc["kwargs"]["n_drop"] == 1 and sc["kwargs"]["hold_thresh"] == 5
    # crossasset_steady's book preserved (the CrossAssetProcessor must stay FIRST in infer_processors)
    assert rc.handler_kwargs["infer_processors"] == cs.handler_kwargs["infer_processors"]
    assert rc.handler_kwargs["infer_processors"][0]["class"] == "CrossAssetProcessor"
    assert rc.universe == cs.universe and rc.segments == cs.segments
    assert rc.handler_kwargs["label"] == cs.handler_kwargs["label"]
    assert rc.model_config["kwargs"] == cs.model_config["kwargs"]
    assert rc.feature_config == cs.feature_config
    assert rc.fee_preset == cs.fee_preset and rc.label_horizon_days == cs.label_horizon_days


# --- linear_steady recipe: steady book + Ridge (sklearn) instead of LGBM (iter-27 model-axis test) ---


def test_linear_steady_is_ridge_on_steady_book():
    ln, st = resolve_recipe("linear_steady"), resolve_recipe("steady")
    mc = ln.model_config
    assert mc["class"] == "Ridge"
    assert mc["module_path"] == "sklearn.linear_model"
    assert mc["kwargs"]["alpha"] == 10.0
    # steady's book preserved (only the model differs)
    assert ln.handler_kwargs == st.handler_kwargs
    assert ln.feature_config == st.feature_config
    assert ln.strategy_config == st.strategy_config
    assert ln.universe == st.universe and ln.segments == st.segments
    assert ln.fee_preset == st.fee_preset and ln.label_horizon_days == st.label_horizon_days


# --- h1/h10/h20_steady recipes: steady's book with different label horizons (iter-28) ---


@pytest.mark.parametrize(
    "name,fwd,horizon",
    [("h1_steady", 2, 2), ("h10_steady", 11, 11), ("h20_steady", 21, 21)],
)
def test_horizon_recipe_is_steady_book_with_changed_label(name, fwd, horizon):
    r, st = resolve_recipe(name), resolve_recipe("steady")
    assert r.handler_kwargs["label"] == ([f"Ref($close, -{fwd})/Ref($close, -1) - 1"], ["LABEL0"])
    assert r.label_horizon_days == horizon
    # rest of steady's book preserved
    assert r.model_config == st.model_config
    assert r.strategy_config == st.strategy_config
    assert r.feature_config == st.feature_config
    assert r.handler_kwargs["infer_processors"] == st.handler_kwargs["infer_processors"]
    assert r.handler_kwargs["learn_processors"] == st.handler_kwargs["learn_processors"]
    assert r.universe == st.universe and r.segments == st.segments
    assert r.fee_preset == st.fee_preset


# --- regime_equalweight recipe: steady book + binary-200 regime gate + no-selection (DummyRegressor, topk=universe) ---


def test_regime_equalweight_is_no_selection_gated_universe():
    ew, st = resolve_recipe("regime_equalweight"), resolve_recipe("steady")
    mc = ew.model_config
    assert ew.model_config == {"class": "DummyRegressor", "module_path": "sklearn.dummy", "kwargs": {"strategy": "mean"}}
    assert mc["class"] == "DummyRegressor"
    sc = ew.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["topk"] == 19  # = universe size -> hold all -> equal-weight
    assert sc["kwargs"]["regime_mode"] == "binary"
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["vol_target"] == 0.50
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert len(ew.universe) == 19  # topk == universe size
    # steady's data book preserved (only model + strategy differ)
    assert ew.handler_kwargs == st.handler_kwargs
    assert ew.feature_config == st.feature_config
    assert ew.universe == st.universe and ew.segments == st.segments
    assert ew.fee_preset == st.fee_preset and ew.label_horizon_days == st.label_horizon_days


# --- regime_equalweight_majors recipe: regime_equalweight on 10-major universe (iter-30 A/B) ---


def test_regime_equalweight_majors_is_10_major_basket():
    rm, ew, st = (
        resolve_recipe("regime_equalweight_majors"),
        resolve_recipe("regime_equalweight"),
        resolve_recipe("steady"),
    )
    majors = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "TRXUSDT")
    assert rm.universe == majors
    assert rm.strategy_config["kwargs"]["topk"] == 10 == len(rm.universe)  # hold-all equal-weight
    # everything else matches regime_equalweight (the iter-29 best): model + the rest of the gate
    assert rm.model_config == ew.model_config  # DummyRegressor
    for k in ("regime_mode", "regime_ma_window", "vol_target", "regime_benchmark", "n_drop", "hold_thresh"):
        assert rm.strategy_config["kwargs"][k] == ew.strategy_config["kwargs"][k]
    # steady's data book preserved (universe is the only data-book change)
    assert rm.handler_kwargs == st.handler_kwargs
    assert rm.feature_config == st.feature_config
    assert rm.segments == st.segments
    assert rm.fee_preset == st.fee_preset and rm.label_horizon_days == st.label_horizon_days


# --- regime_equalweight_top5 recipe: regime_equalweight_majors on 5-megacap universe (iter-31 A/B) ---


def test_regime_equalweight_top5_is_5_megacap_basket():
    t5, mj, st = (
        resolve_recipe("regime_equalweight_top5"),
        resolve_recipe("regime_equalweight_majors"),
        resolve_recipe("steady"),
    )
    mega = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
    assert t5.universe == mega
    assert t5.strategy_config["kwargs"]["topk"] == 5 == len(t5.universe)  # hold-all equal-weight
    # everything else matches the 10-major best: model + the rest of the gate
    assert t5.model_config == mj.model_config  # DummyRegressor
    for k in ("regime_mode", "regime_ma_window", "vol_target", "regime_benchmark", "n_drop", "hold_thresh"):
        assert t5.strategy_config["kwargs"][k] == mj.strategy_config["kwargs"][k]
    # steady's data book preserved (universe is the only data-book change)
    assert t5.handler_kwargs == st.handler_kwargs
    assert t5.feature_config == st.feature_config
    assert t5.segments == st.segments
    assert t5.fee_preset == st.fee_preset and t5.label_horizon_days == st.label_horizon_days


# --- regime_volweight_majors recipe: inverse-vol gated basket of 10 majors (iter-32 A/B) ---


def test_regime_volweight_majors_is_volweighted_gated_10major():
    rv, st = resolve_recipe("regime_volweight_majors"), resolve_recipe("steady")
    majors = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "TRXUSDT")
    sc = rv.strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert tuple(sc["kwargs"]["weight_universe"]) == majors
    assert sc["kwargs"]["regime_mode"] == "binary"
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["vol_target"] == 0.50
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert rv.model_config["class"] == "DummyRegressor"
    assert rv.universe == majors
    # steady's data book preserved
    assert rv.handler_kwargs == st.handler_kwargs
    assert rv.feature_config == st.feature_config
    assert rv.segments == st.segments
    assert rv.fee_preset == st.fee_preset and rv.label_horizon_days == st.label_horizon_days


# --- beta_null recipe: pre-registered passive-beta-timing null/yardstick (iter-34 Stage-0) ---


def test_beta_null_resolves_and_frozen_params():
    r = resolve_recipe("beta_null")
    assert r.name == "beta_null"
    sc = r.strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    # frozen gate params
    assert sc["kwargs"]["vol_target"] == 0.50
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["regime_mode"] == "binary"
    # membership filter
    assert sc["kwargs"]["membership_top_n"] == 10
    assert sc["kwargs"]["membership_lookback_days"] == 30
    # model
    assert r.model_config["class"] == "DummyRegressor"
    assert r.model_config["module_path"] == "sklearn.dummy"
    # label / fee
    assert r.fee_preset == "vip2_bnb"
    assert r.label_horizon_days == 6


def test_beta_null_universe_is_full_liquid_set():
    r = resolve_recipe("beta_null")
    ew = resolve_recipe("regime_equalweight")
    rv = resolve_recipe("regime_volweight_majors")
    # broader than the 10-major set
    assert len(r.universe) > len(rv.universe)
    # matches the full 19-coin liquid set used by regime_equalweight
    assert r.universe == ew.universe
    # weight_universe also covers the full set
    sc = r.strategy_config
    assert tuple(sc["kwargs"]["weight_universe"]) == ew.universe


def test_beta_null_non_lever_fields_match_steady():
    r, st = resolve_recipe("beta_null"), resolve_recipe("steady")
    assert r.segments == st.segments
    assert r.account == st.account
    assert r.benchmark == st.benchmark
    assert r.fee_preset == st.fee_preset
    assert r.handler_kwargs == st.handler_kwargs
    assert r.feature_config == st.feature_config
    assert r.label_horizon_days == st.label_horizon_days
