"""Tests for the calibrated execution-cost constants module."""


def test_cost_calibration_shape():
    from cli.experiment.costs import COST_CALIBRATION

    assert set(COST_CALIBRATION) >= {"impact_cost", "maker_fill_haircut", "tiers"}
    assert isinstance(COST_CALIBRATION["impact_cost"], float)
    assert isinstance(COST_CALIBRATION["maker_fill_haircut"], float)
    assert COST_CALIBRATION["impact_cost"] >= 0.0
    assert COST_CALIBRATION["maker_fill_haircut"] >= 0.0
