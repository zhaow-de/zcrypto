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
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert sc["kwargs"]["weight_vol_lookback"] == 30
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


# --- tsmom_voltarget recipe: beta_null + per-asset TSMOM gate (iter-35 Stage-1) ---


def test_tsmom_voltarget_resolves_and_has_trend_window():
    r = resolve_recipe("tsmom_voltarget")
    assert r.name == "tsmom_voltarget"
    sc = r.strategy_config
    assert sc["kwargs"]["trend_window"] == 100


def test_tsmom_voltarget_frozen_params_match_beta_null():
    r = resolve_recipe("tsmom_voltarget")
    sc = r.strategy_config
    # frozen params inherited from beta_null
    assert sc["kwargs"]["vol_target"] == 0.50
    assert sc["kwargs"]["weight_vol_lookback"] == 30
    assert sc["kwargs"]["membership_top_n"] == 10
    assert sc["kwargs"]["membership_lookback_days"] == 30
    # market gate params still present (strategy ignores them when trend_window is set)
    assert sc["kwargs"]["regime_mode"] == "binary"
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    # model
    assert r.model_config["class"] == "DummyRegressor"
    assert r.model_config["module_path"] == "sklearn.dummy"
    # fee / label
    assert r.fee_preset == "vip2_bnb"
    assert r.label_horizon_days == 6


def test_tsmom_voltarget_universe_matches_beta_null():
    r, bn = resolve_recipe("tsmom_voltarget"), resolve_recipe("beta_null")
    assert r.universe == bn.universe
    assert tuple(r.strategy_config["kwargs"]["weight_universe"]) == bn.universe


def test_tsmom_voltarget_non_lever_fields_match_beta_null():
    r, bn = resolve_recipe("tsmom_voltarget"), resolve_recipe("beta_null")
    assert r.segments == bn.segments
    assert r.account == bn.account
    assert r.benchmark == bn.benchmark
    assert r.fee_preset == bn.fee_preset
    assert r.handler_kwargs == bn.handler_kwargs
    assert r.feature_config == bn.feature_config
    assert r.label_horizon_days == bn.label_horizon_days


def test_tsmom_voltarget_w200_is_tsmom_at_200d_window():
    r = resolve_recipe("tsmom_voltarget_w200")
    t100 = resolve_recipe("tsmom_voltarget")
    bn = resolve_recipe("beta_null")
    assert r.name == "tsmom_voltarget_w200"
    # the ONLY change vs tsmom_voltarget is the trend window (100 -> 200)
    assert r.strategy_config["kwargs"]["trend_window"] == 200
    assert t100.strategy_config["kwargs"]["trend_window"] == 100
    r_kw = {k: v for k, v in r.strategy_config["kwargs"].items() if k != "trend_window"}
    t_kw = {k: v for k, v in t100.strategy_config["kwargs"].items() if k != "trend_window"}
    assert r_kw == t_kw
    # non-lever fields still match the beta_null book
    assert r.universe == bn.universe
    assert r.segments == bn.segments
    assert r.fee_preset == bn.fee_preset == "vip2_bnb"
    assert r.label_horizon_days == bn.label_horizon_days


def test_tsmom_compose_is_tsmom_plus_compose_flag():
    r = resolve_recipe("tsmom_compose")
    t100 = resolve_recipe("tsmom_voltarget")
    bn = resolve_recipe("beta_null")
    assert r.name == "tsmom_compose"
    # composes per-asset selection (trend_window) WITH the market gate (compose flag)
    assert r.strategy_config["kwargs"]["trend_window"] == 100
    assert r.strategy_config["kwargs"]["compose_market_gate"] is True
    # the ONLY change vs tsmom_voltarget is the compose flag (replace-mode default is False/absent)
    assert t100.strategy_config["kwargs"].get("compose_market_gate", False) is False
    r_kw = {k: v for k, v in r.strategy_config["kwargs"].items() if k != "compose_market_gate"}
    t_kw = {k: v for k, v in t100.strategy_config["kwargs"].items() if k != "compose_market_gate"}
    assert r_kw == t_kw
    # non-lever fields still match the beta_null book
    assert r.universe == bn.universe
    assert r.segments == bn.segments
    assert r.fee_preset == bn.fee_preset == "vip2_bnb"
    assert r.label_horizon_days == bn.label_horizon_days


# --- basis_froth recipe: beta_null + basis-froth de-risk overlay (iter-39 Stage-2) ---

_FROTH_KEYS = {"froth_field", "froth_lookback", "froth_z_threshold", "froth_derisk_mult"}


def test_basis_froth_resolves():
    r = resolve_recipe("basis_froth")
    assert r.name == "basis_froth"


def test_basis_froth_froth_params():
    sc = resolve_recipe("basis_froth").strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["froth_field"] == "$basis"
    assert sc["kwargs"]["froth_lookback"] == 90
    assert sc["kwargs"]["froth_z_threshold"] == 1.5
    assert sc["kwargs"]["froth_derisk_mult"] == 0.0


def test_basis_froth_only_froth_keys_differ_from_beta_null():
    """The ONLY strategy-kwargs delta vs beta_null is the four froth keys (drift guard)."""
    bf_kw = resolve_recipe("basis_froth").strategy_config["kwargs"]
    bn_kw = resolve_recipe("beta_null").strategy_config["kwargs"]
    assert {k: v for k, v in bf_kw.items() if k not in _FROTH_KEYS} == bn_kw


def test_basis_froth_non_lever_fields_match_beta_null():
    bf, bn = resolve_recipe("basis_froth"), resolve_recipe("beta_null")
    assert bf.universe == bn.universe
    assert bf.segments == bn.segments
    assert bf.fee_preset == bn.fee_preset
    assert bf.label_horizon_days == bn.label_horizon_days
    assert bf.account == bn.account
    assert bf.benchmark == bn.benchmark
    assert bf.reference_instruments == bn.reference_instruments
    assert bf.handler_kwargs == bn.handler_kwargs
    assert bf.feature_config == bn.feature_config


# --- basis_tilt recipe: beta_null + cross-sectional crowding-weighting tilt (iter-40 Stage-2) ---

_CROWDING_KEYS = {"crowding_field", "crowding_tilt_k"}


def test_basis_tilt_resolves():
    r = resolve_recipe("basis_tilt")
    assert r.name == "basis_tilt"


def test_basis_tilt_crowding_params():
    sc = resolve_recipe("basis_tilt").strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["crowding_field"] == "$basis"
    assert sc["kwargs"]["crowding_tilt_k"] == 1.0


def test_basis_tilt_only_crowding_keys_differ_from_beta_null():
    """The ONLY strategy-kwargs delta vs beta_null is the two crowding keys (drift guard)."""
    bt_kw = resolve_recipe("basis_tilt").strategy_config["kwargs"]
    bn_kw = resolve_recipe("beta_null").strategy_config["kwargs"]
    assert {k: v for k, v in bt_kw.items() if k not in _CROWDING_KEYS} == bn_kw


def test_basis_tilt_non_lever_fields_match_beta_null():
    bt, bn = resolve_recipe("basis_tilt"), resolve_recipe("beta_null")
    assert bt.universe == bn.universe
    assert bt.segments == bn.segments
    assert bt.fee_preset == bn.fee_preset
    assert bt.label_horizon_days == bn.label_horizon_days
    assert bt.account == bn.account
    assert bt.benchmark == bn.benchmark
    assert bt.reference_instruments == bn.reference_instruments
    assert bt.handler_kwargs == bn.handler_kwargs
    assert bt.feature_config == bn.feature_config


# --- oi_divergence_tilt recipe: beta_null + OI-price-divergence tilt (iter-41 Stage-2) ---

_OI_DIV_KEYS = {"oi_divergence", "oi_div_lookback", "oi_div_tilt_k"}


def test_oi_divergence_tilt_resolves():
    r = resolve_recipe("oi_divergence_tilt")
    assert r.name == "oi_divergence_tilt"


def test_oi_divergence_tilt_oi_div_params():
    sc = resolve_recipe("oi_divergence_tilt").strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["oi_divergence"] is True
    assert sc["kwargs"]["oi_div_lookback"] == 14
    assert sc["kwargs"]["oi_div_tilt_k"] == 1.0


def test_oi_divergence_tilt_only_oi_div_keys_differ_from_beta_null():
    """The ONLY strategy-kwargs delta vs beta_null is the three oi-div keys (drift guard)."""
    oi_kw = resolve_recipe("oi_divergence_tilt").strategy_config["kwargs"]
    bn_kw = resolve_recipe("beta_null").strategy_config["kwargs"]
    assert {k: v for k, v in oi_kw.items() if k not in _OI_DIV_KEYS} == bn_kw


def test_oi_divergence_tilt_non_lever_fields_match_beta_null():
    oi, bn = resolve_recipe("oi_divergence_tilt"), resolve_recipe("beta_null")
    assert oi.universe == bn.universe
    assert oi.segments == bn.segments
    assert oi.fee_preset == bn.fee_preset
    assert oi.label_horizon_days == bn.label_horizon_days
    assert oi.account == bn.account
    assert oi.benchmark == bn.benchmark
    assert oi.reference_instruments == bn.reference_instruments
    assert oi.handler_kwargs == bn.handler_kwargs
    assert oi.feature_config == bn.feature_config


def test_oi_divergence_tilt_directional_defaults_false():
    """iter-41 oi_divergence_tilt recipe: oi_div_directional absent/defaults to False (back-compat)."""
    sc = resolve_recipe("oi_divergence_tilt").strategy_config
    assert sc["kwargs"].get("oi_div_directional", False) is False


# --- oi_divergence_directional recipe: beta_null + directional OI-div tilt (iter-42 Stage-2) ---

_OI_DIV_DIRECTIONAL_KEYS = {"oi_divergence", "oi_div_directional", "oi_div_lookback", "oi_div_tilt_k"}


def test_oi_divergence_directional_resolves():
    r = resolve_recipe("oi_divergence_directional")
    assert r.name == "oi_divergence_directional"


def test_oi_divergence_directional_params():
    sc = resolve_recipe("oi_divergence_directional").strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["oi_divergence"] is True
    assert sc["kwargs"]["oi_div_directional"] is True
    assert sc["kwargs"]["oi_div_lookback"] == 14
    assert sc["kwargs"]["oi_div_tilt_k"] == 1.0


def test_oi_divergence_directional_only_oi_div_keys_differ_from_beta_null():
    """The ONLY strategy-kwargs delta vs beta_null is the four oi-div keys (drift guard)."""
    od_kw = resolve_recipe("oi_divergence_directional").strategy_config["kwargs"]
    bn_kw = resolve_recipe("beta_null").strategy_config["kwargs"]
    assert {k: v for k, v in od_kw.items() if k not in _OI_DIV_DIRECTIONAL_KEYS} == bn_kw


def test_oi_divergence_directional_non_lever_fields_match_beta_null():
    od, bn = resolve_recipe("oi_divergence_directional"), resolve_recipe("beta_null")
    assert od.universe == bn.universe
    assert od.segments == bn.segments
    assert od.fee_preset == bn.fee_preset
    assert od.label_horizon_days == bn.label_horizon_days
    assert od.account == bn.account
    assert od.benchmark == bn.benchmark
    assert od.reference_instruments == bn.reference_instruments
    assert od.handler_kwargs == bn.handler_kwargs
    assert od.feature_config == bn.feature_config


# --- smart_money_tilt recipe: beta_null + smart-money L/S divergence tilt (iter-43 Stage-2) ---

_SMART_MONEY_KEYS = {"smart_money", "smart_money_tilt_k"}


def test_smart_money_tilt_resolves():
    r = resolve_recipe("smart_money_tilt")
    assert r.name == "smart_money_tilt"


def test_smart_money_tilt_params():
    sc = resolve_recipe("smart_money_tilt").strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["smart_money"] is True
    assert sc["kwargs"]["smart_money_tilt_k"] == 1.0


def test_smart_money_tilt_only_smart_money_keys_differ_from_beta_null():
    """The ONLY strategy-kwargs delta vs beta_null is the two smart-money keys (drift guard)."""
    sm_kw = resolve_recipe("smart_money_tilt").strategy_config["kwargs"]
    bn_kw = resolve_recipe("beta_null").strategy_config["kwargs"]
    assert {k: v for k, v in sm_kw.items() if k not in _SMART_MONEY_KEYS} == bn_kw


def test_smart_money_tilt_non_lever_fields_match_beta_null():
    sm, bn = resolve_recipe("smart_money_tilt"), resolve_recipe("beta_null")
    assert sm.universe == bn.universe
    assert sm.segments == bn.segments
    assert sm.fee_preset == bn.fee_preset
    assert sm.label_horizon_days == bn.label_horizon_days
    assert sm.account == bn.account
    assert sm.benchmark == bn.benchmark
    assert sm.reference_instruments == bn.reference_instruments
    assert sm.handler_kwargs == bn.handler_kwargs
    assert sm.feature_config == bn.feature_config


# --- oi_div_strong_trend recipe: beta_null + strong-trend-gated directional OI-div tilt (iter-44) ---

_OI_DIV_STRONG_TREND_KEYS = {
    "oi_divergence",
    "oi_div_directional",
    "oi_div_lookback",
    "oi_div_tilt_k",
    "oi_div_strong_trend_only",
    "oi_div_strong_trend_margin",
}


def test_oi_div_strong_trend_resolves():
    r = resolve_recipe("oi_div_strong_trend")
    assert r.name == "oi_div_strong_trend"


def test_oi_div_strong_trend_params():
    sc = resolve_recipe("oi_div_strong_trend").strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["oi_divergence"] is True
    assert sc["kwargs"]["oi_div_directional"] is True
    assert sc["kwargs"]["oi_div_lookback"] == 14
    assert sc["kwargs"]["oi_div_tilt_k"] == 1.0
    assert sc["kwargs"]["oi_div_strong_trend_only"] is True
    assert sc["kwargs"]["oi_div_strong_trend_margin"] == 0.25


def test_oi_div_strong_trend_only_six_keys_differ_from_beta_null():
    """The ONLY strategy-kwargs delta vs beta_null is the six oi-div keys (drift guard)."""
    st_kw = resolve_recipe("oi_div_strong_trend").strategy_config["kwargs"]
    bn_kw = resolve_recipe("beta_null").strategy_config["kwargs"]
    assert {k: v for k, v in st_kw.items() if k not in _OI_DIV_STRONG_TREND_KEYS} == bn_kw


def test_oi_div_strong_trend_non_lever_fields_match_beta_null():
    st, bn = resolve_recipe("oi_div_strong_trend"), resolve_recipe("beta_null")
    assert st.universe == bn.universe
    assert st.segments == bn.segments
    assert st.fee_preset == bn.fee_preset
    assert st.label_horizon_days == bn.label_horizon_days
    assert st.account == bn.account
    assert st.benchmark == bn.benchmark
    assert st.reference_instruments == bn.reference_instruments
    assert st.handler_kwargs == bn.handler_kwargs
    assert st.feature_config == bn.feature_config


def test_oi_divergence_directional_still_resolves_without_strong_trend_keys():
    """iter-42 recipe is unchanged: strong-trend keys are absent (default False/0.25)."""
    od = resolve_recipe("oi_divergence_directional")
    assert od.name == "oi_divergence_directional"
    kw = od.strategy_config["kwargs"]
    assert kw.get("oi_div_strong_trend_only", False) is False
    assert "oi_div_strong_trend_margin" not in kw


# --- derivatives_steady recipe: steady book + DerivativesProcessor (iter-45 Stage-2) ---


def test_derivatives_steady_resolves():
    r = resolve_recipe("derivatives_steady")
    assert r.name == "derivatives_steady"


def test_derivatives_steady_wires_processor_and_matches_steady_book():
    import dataclasses

    from cli.experiment.recipes.base import resolve_recipe

    ds = resolve_recipe("derivatives_steady")
    steady = resolve_recipe("steady")
    # DerivativesProcessor is prepended first, before RobustZScoreNorm.
    assert _infer_classes(ds)[0] == "DerivativesProcessor"
    assert _infer_classes(ds)[1] == "RobustZScoreNorm"
    # Book matches steady except name + infer_processors (clean A/B isolation).
    assert dataclasses.replace(ds, name="steady", handler_kwargs=steady.handler_kwargs) == steady


def test_derivatives_steady_processor_module_path():
    ds = resolve_recipe("derivatives_steady")
    proc = ds.handler_kwargs["infer_processors"][0]
    assert proc["class"] == "DerivativesProcessor"
    assert proc["module_path"] == "cli.experiment.features.derivatives"


def test_derivatives_steady_learn_processors_match_steady():
    ds = resolve_recipe("derivatives_steady")
    steady = resolve_recipe("steady")
    assert ds.handler_kwargs["learn_processors"] == steady.handler_kwargs["learn_processors"]


def test_derivatives_steady_model_config_matches_steady():
    ds = resolve_recipe("derivatives_steady")
    steady = resolve_recipe("steady")
    assert ds.model_config == steady.model_config


def test_derivatives_steady_strategy_config_matches_steady():
    ds = resolve_recipe("derivatives_steady")
    steady = resolve_recipe("steady")
    assert ds.strategy_config == steady.strategy_config


def test_derivatives_steady_non_lever_fields_match_steady():
    ds = resolve_recipe("derivatives_steady")
    steady = resolve_recipe("steady")
    assert ds.universe == steady.universe
    assert ds.segments == steady.segments
    assert ds.fee_preset == steady.fee_preset
    assert ds.account == steady.account
    assert ds.benchmark == steady.benchmark
    assert ds.reference_instruments == steady.reference_instruments
    assert ds.feature_config == steady.feature_config
    assert ds.label_horizon_days == steady.label_horizon_days
    assert ds.feature_lookback_days == steady.feature_lookback_days
    assert ds.cv_n_groups == steady.cv_n_groups
    assert ds.cv_test_groups == steady.cv_test_groups


# --- onchain_regime recipe: beta_null + NVM on-chain de-risk overlay (iter-46 Stage-2) ---

_ONCHAIN_KEYS = {"onchain_regime", "onchain_path", "onchain_z_threshold", "onchain_derisk_mult", "onchain_z_window"}


def test_onchain_regime_resolves():
    r = resolve_recipe("onchain_regime")
    assert r.name == "onchain_regime"


def test_onchain_regime_has_onchain_kwargs():
    sc = resolve_recipe("onchain_regime").strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["onchain_regime"] is True
    assert sc["kwargs"]["onchain_path"] == "data/onchain/btc_nvm.parquet"
    assert sc["kwargs"]["onchain_z_threshold"] == 1.0
    assert sc["kwargs"]["onchain_derisk_mult"] == 0.0
    assert sc["kwargs"]["onchain_z_window"] == 365


def test_onchain_regime_only_onchain_keys_differ_from_beta_null():
    """The ONLY strategy-kwargs delta vs beta_null is the five onchain_* keys (drift guard)."""
    oc_kw = resolve_recipe("onchain_regime").strategy_config["kwargs"]
    bn_kw = resolve_recipe("beta_null").strategy_config["kwargs"]
    assert {k: v for k, v in oc_kw.items() if k not in _ONCHAIN_KEYS} == bn_kw


def test_onchain_regime_non_lever_fields_match_beta_null():
    oc, bn = resolve_recipe("onchain_regime"), resolve_recipe("beta_null")
    assert oc.universe == bn.universe
    assert oc.segments == bn.segments
    assert oc.fee_preset == bn.fee_preset
    assert oc.label_horizon_days == bn.label_horizon_days
    assert oc.account == bn.account
    assert oc.benchmark == bn.benchmark
    assert oc.reference_instruments == bn.reference_instruments
    assert oc.handler_kwargs == bn.handler_kwargs
    assert oc.feature_config == bn.feature_config


# --- momentum_tilt recipe: beta_null + cross-sectional momentum tilt (iter-47 Stage-2) ---

_MOMENTUM_KEYS = {"momentum_tilt", "momentum_lookback", "momentum_tilt_k"}


def test_momentum_tilt_resolves():
    r = resolve_recipe("momentum_tilt")
    assert r.name == "momentum_tilt"


def test_momentum_tilt_params():
    sc = resolve_recipe("momentum_tilt").strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["momentum_tilt"] is True
    assert sc["kwargs"]["momentum_lookback"] == 30
    assert sc["kwargs"]["momentum_tilt_k"] == 1.0


def test_momentum_tilt_only_momentum_keys_differ_from_beta_null():
    """The ONLY strategy-kwargs delta vs beta_null is the three momentum keys (drift guard)."""
    mt_kw = resolve_recipe("momentum_tilt").strategy_config["kwargs"]
    bn_kw = resolve_recipe("beta_null").strategy_config["kwargs"]
    assert {k: v for k, v in mt_kw.items() if k not in _MOMENTUM_KEYS} == bn_kw


def test_momentum_tilt_non_lever_fields_match_beta_null():
    mt, bn = resolve_recipe("momentum_tilt"), resolve_recipe("beta_null")
    assert mt.universe == bn.universe
    assert mt.segments == bn.segments
    assert mt.fee_preset == bn.fee_preset
    assert mt.label_horizon_days == bn.label_horizon_days
    assert mt.account == bn.account
    assert mt.benchmark == bn.benchmark
    assert mt.reference_instruments == bn.reference_instruments
    assert mt.handler_kwargs == bn.handler_kwargs
    assert mt.feature_config == bn.feature_config


# --- momentum_tilt_l14/l60/l90 recipes: iter-48 lookback-robustness sweep ---


import pytest


@pytest.mark.parametrize(
    "recipe_name,expected_lookback",
    [
        ("momentum_tilt_l14", 14),
        ("momentum_tilt_l60", 60),
        ("momentum_tilt_l90", 90),
    ],
)
def test_momentum_tilt_lookback_variant_resolves(recipe_name, expected_lookback):
    r = resolve_recipe(recipe_name)
    assert r.name == recipe_name


@pytest.mark.parametrize(
    "recipe_name,expected_lookback",
    [
        ("momentum_tilt_l14", 14),
        ("momentum_tilt_l60", 60),
        ("momentum_tilt_l90", 90),
    ],
)
def test_momentum_tilt_lookback_variant_params(recipe_name, expected_lookback):
    sc = resolve_recipe(recipe_name).strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["momentum_tilt"] is True
    assert sc["kwargs"]["momentum_lookback"] == expected_lookback
    assert sc["kwargs"]["momentum_tilt_k"] == 1.0


@pytest.mark.parametrize(
    "recipe_name,expected_lookback",
    [
        ("momentum_tilt_l14", 14),
        ("momentum_tilt_l60", 60),
        ("momentum_tilt_l90", 90),
    ],
)
def test_momentum_tilt_lookback_variant_only_momentum_keys_differ_from_beta_null(recipe_name, expected_lookback):
    """The ONLY strategy-kwargs delta vs beta_null is the three momentum keys (drift guard)."""
    variant_kw = resolve_recipe(recipe_name).strategy_config["kwargs"]
    bn_kw = resolve_recipe("beta_null").strategy_config["kwargs"]
    assert {k: v for k, v in variant_kw.items() if k not in _MOMENTUM_KEYS} == bn_kw


@pytest.mark.parametrize(
    "recipe_name,expected_lookback",
    [
        ("momentum_tilt_l14", 14),
        ("momentum_tilt_l60", 60),
        ("momentum_tilt_l90", 90),
    ],
)
def test_momentum_tilt_lookback_variant_non_lever_fields_match_beta_null(recipe_name, expected_lookback):
    variant, bn = resolve_recipe(recipe_name), resolve_recipe("beta_null")
    assert variant.universe == bn.universe
    assert variant.segments == bn.segments
    assert variant.fee_preset == bn.fee_preset
    assert variant.label_horizon_days == bn.label_horizon_days
    assert variant.account == bn.account
    assert variant.benchmark == bn.benchmark
    assert variant.reference_instruments == bn.reference_instruments
    assert variant.handler_kwargs == bn.handler_kwargs
    assert variant.feature_config == bn.feature_config


# --- momentum_tilt_k05/k15/k20 recipes: iter-50 k-strength dose-response sweep ---


@pytest.mark.parametrize(
    "recipe_name,expected_k",
    [
        ("momentum_tilt_k05", 0.5),
        ("momentum_tilt_k15", 1.5),
        ("momentum_tilt_k20", 2.0),
    ],
)
def test_momentum_tilt_k_variant_resolves(recipe_name, expected_k):
    r = resolve_recipe(recipe_name)
    assert r.name == recipe_name


@pytest.mark.parametrize(
    "recipe_name,expected_k",
    [
        ("momentum_tilt_k05", 0.5),
        ("momentum_tilt_k15", 1.5),
        ("momentum_tilt_k20", 2.0),
    ],
)
def test_momentum_tilt_k_variant_params(recipe_name, expected_k):
    sc = resolve_recipe(recipe_name).strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["momentum_tilt"] is True
    assert sc["kwargs"]["momentum_lookback"] == 30
    assert sc["kwargs"]["momentum_tilt_k"] == expected_k


@pytest.mark.parametrize(
    "recipe_name,expected_k",
    [
        ("momentum_tilt_k05", 0.5),
        ("momentum_tilt_k15", 1.5),
        ("momentum_tilt_k20", 2.0),
    ],
)
def test_momentum_tilt_k_variant_only_momentum_keys_differ_from_beta_null(recipe_name, expected_k):
    """The ONLY strategy-kwargs delta vs beta_null is the three momentum keys (drift guard)."""
    variant_kw = resolve_recipe(recipe_name).strategy_config["kwargs"]
    bn_kw = resolve_recipe("beta_null").strategy_config["kwargs"]
    assert {k: v for k, v in variant_kw.items() if k not in _MOMENTUM_KEYS} == bn_kw


@pytest.mark.parametrize(
    "recipe_name,expected_k",
    [
        ("momentum_tilt_k05", 0.5),
        ("momentum_tilt_k15", 1.5),
        ("momentum_tilt_k20", 2.0),
    ],
)
def test_momentum_tilt_k_variant_non_lever_fields_match_beta_null(recipe_name, expected_k):
    variant, bn = resolve_recipe(recipe_name), resolve_recipe("beta_null")
    assert variant.universe == bn.universe
    assert variant.segments == bn.segments
    assert variant.fee_preset == bn.fee_preset
    assert variant.label_horizon_days == bn.label_horizon_days
    assert variant.account == bn.account
    assert variant.benchmark == bn.benchmark
    assert variant.reference_instruments == bn.reference_instruments
    assert variant.handler_kwargs == bn.handler_kwargs
    assert variant.feature_config == bn.feature_config


# --- momentum_tilt_hicost / beta_null_hicost recipes: iter-49 cost-sensitivity A/B ---

_HICOST_MAKER_FILL = 0.00043309643984270344


def test_momentum_tilt_hicost_resolves():
    r = resolve_recipe("momentum_tilt_hicost")
    assert r.name == "momentum_tilt_hicost"


def test_momentum_tilt_hicost_maker_fill_haircut():
    r = resolve_recipe("momentum_tilt_hicost")
    assert r.maker_fill_haircut == _HICOST_MAKER_FILL


def test_momentum_tilt_hicost_only_name_and_haircut_differ_from_momentum_tilt():
    """momentum_tilt_hicost differs from momentum_tilt ONLY by name + maker_fill_haircut."""
    hc = resolve_recipe("momentum_tilt_hicost")
    mt = resolve_recipe("momentum_tilt")
    assert hc.strategy_config == mt.strategy_config
    assert hc.model_config == mt.model_config
    assert hc.universe == mt.universe
    assert hc.segments == mt.segments
    assert hc.fee_preset == mt.fee_preset
    assert hc.label_horizon_days == mt.label_horizon_days
    assert hc.feature_lookback_days == mt.feature_lookback_days
    assert hc.account == mt.account
    assert hc.benchmark == mt.benchmark
    assert hc.reference_instruments == mt.reference_instruments
    assert hc.handler_kwargs == mt.handler_kwargs
    assert hc.feature_config == mt.feature_config
    assert hc.impact_cost == mt.impact_cost
    assert hc.fees_only == mt.fees_only
    assert hc.cv_n_groups == mt.cv_n_groups
    assert hc.cv_test_groups == mt.cv_test_groups


def test_beta_null_hicost_resolves():
    r = resolve_recipe("beta_null_hicost")
    assert r.name == "beta_null_hicost"


def test_beta_null_hicost_maker_fill_haircut():
    r = resolve_recipe("beta_null_hicost")
    assert r.maker_fill_haircut == _HICOST_MAKER_FILL


def test_beta_null_hicost_only_name_and_haircut_differ_from_beta_null():
    """beta_null_hicost differs from beta_null ONLY by name + maker_fill_haircut."""
    hc = resolve_recipe("beta_null_hicost")
    bn = resolve_recipe("beta_null")
    assert hc.strategy_config == bn.strategy_config
    assert hc.model_config == bn.model_config
    assert hc.universe == bn.universe
    assert hc.segments == bn.segments
    assert hc.fee_preset == bn.fee_preset
    assert hc.label_horizon_days == bn.label_horizon_days
    assert hc.feature_lookback_days == bn.feature_lookback_days
    assert hc.account == bn.account
    assert hc.benchmark == bn.benchmark
    assert hc.reference_instruments == bn.reference_instruments
    assert hc.handler_kwargs == bn.handler_kwargs
    assert hc.feature_config == bn.feature_config
    assert hc.impact_cost == bn.impact_cost
    assert hc.fees_only == bn.fees_only
    assert hc.cv_n_groups == bn.cv_n_groups
    assert hc.cv_test_groups == bn.cv_test_groups


# --- beta_null_confirm5 recipe: beta_null + 5-day anti-whipsaw confirmation filter (iter-53) ---

_CONFIRM5_KEY = "regime_confirm_days"


def test_beta_null_confirm5_resolves():
    r = resolve_recipe("beta_null_confirm5")
    assert r.name == "beta_null_confirm5"


def test_beta_null_confirm5_confirm_days_param():
    sc = resolve_recipe("beta_null_confirm5").strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"][_CONFIRM5_KEY] == 5


def test_beta_null_confirm5_only_confirm_key_differs_from_beta_null():
    """The ONLY strategy-kwargs delta vs beta_null is regime_confirm_days=5 (drift guard)."""
    c5_kw = resolve_recipe("beta_null_confirm5").strategy_config["kwargs"]
    bn_kw = resolve_recipe("beta_null").strategy_config["kwargs"]
    assert {k: v for k, v in c5_kw.items() if k != _CONFIRM5_KEY} == bn_kw


def test_beta_null_confirm5_non_lever_fields_match_beta_null():
    c5, bn = resolve_recipe("beta_null_confirm5"), resolve_recipe("beta_null")
    assert c5.universe == bn.universe
    assert c5.segments == bn.segments
    assert c5.fee_preset == bn.fee_preset
    assert c5.label_horizon_days == bn.label_horizon_days
    assert c5.account == bn.account
    assert c5.benchmark == bn.benchmark
    assert c5.reference_instruments == bn.reference_instruments
    assert c5.handler_kwargs == bn.handler_kwargs
    assert c5.feature_config == bn.feature_config


# --- beta_null_confirm2/3/10 recipes: iter-54 anti-whipsaw confirm-days N-sweep ---

_CONFIRM_KEY = "regime_confirm_days"


@pytest.mark.parametrize(
    "recipe_name,expected_days",
    [
        ("beta_null_confirm2", 2),
        ("beta_null_confirm3", 3),
        ("beta_null_confirm10", 10),
    ],
)
def test_beta_null_confirm_sweep_resolves(recipe_name, expected_days):
    r = resolve_recipe(recipe_name)
    assert r.name == recipe_name


@pytest.mark.parametrize(
    "recipe_name,expected_days",
    [
        ("beta_null_confirm2", 2),
        ("beta_null_confirm3", 3),
        ("beta_null_confirm10", 10),
    ],
)
def test_beta_null_confirm_sweep_confirm_days_param(recipe_name, expected_days):
    sc = resolve_recipe(recipe_name).strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"][_CONFIRM_KEY] == expected_days


@pytest.mark.parametrize(
    "recipe_name,expected_days",
    [
        ("beta_null_confirm2", 2),
        ("beta_null_confirm3", 3),
        ("beta_null_confirm10", 10),
    ],
)
def test_beta_null_confirm_sweep_only_confirm_key_differs_from_beta_null(recipe_name, expected_days):
    """The ONLY strategy-kwargs delta vs beta_null is regime_confirm_days (drift guard)."""
    variant_kw = resolve_recipe(recipe_name).strategy_config["kwargs"]
    bn_kw = resolve_recipe("beta_null").strategy_config["kwargs"]
    assert {k: v for k, v in variant_kw.items() if k != _CONFIRM_KEY} == bn_kw


@pytest.mark.parametrize(
    "recipe_name,expected_days",
    [
        ("beta_null_confirm2", 2),
        ("beta_null_confirm3", 3),
        ("beta_null_confirm10", 10),
    ],
)
def test_beta_null_confirm_sweep_non_lever_fields_match_beta_null(recipe_name, expected_days):
    variant, bn = resolve_recipe(recipe_name), resolve_recipe("beta_null")
    assert variant.universe == bn.universe
    assert variant.segments == bn.segments
    assert variant.fee_preset == bn.fee_preset
    assert variant.label_horizon_days == bn.label_horizon_days
    assert variant.account == bn.account
    assert variant.benchmark == bn.benchmark
    assert variant.reference_instruments == bn.reference_instruments
    assert variant.handler_kwargs == bn.handler_kwargs
    assert variant.feature_config == bn.feature_config
