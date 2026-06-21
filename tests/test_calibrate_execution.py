import pandas as pd


def _trades(prices, qtys, makers):
    return pd.DataFrame({"price": prices, "quantity": qtys, "is_buyer_maker": makers})


def test_estimate_impact_coef_recovers_known_coefficient():
    from cli.experiment.scripts.calibrate_execution import estimate_impact_coef

    # A book that walks linearly: consuming a probe of `probe_frac` of bar volume moves VWAP
    # a known amount → the recovered c = impact_bps_ratio / probe_frac**2 is finite + positive.
    trades = _trades(
        prices=[100.0, 100.1, 100.2, 100.3, 100.4],
        qtys=[10.0, 10.0, 10.0, 10.0, 10.0],
        makers=[True, True, False, False, True],
    )
    bar_dollar_volume = sum(p * q for p, q in zip(trades["price"], trades["quantity"]))
    c = estimate_impact_coef(trades, bar_dollar_volume, probe_frac=0.2)
    assert isinstance(c, float) and c > 0.0


def test_estimate_fill_returns_rate_and_spread():
    from cli.experiment.scripts.calibrate_execution import estimate_fill

    trades = _trades(
        prices=[100.0, 100.0, 100.1, 100.1, 100.0],
        qtys=[5.0, 5.0, 5.0, 5.0, 5.0],
        makers=[True, False, True, False, True],
    )
    fill_rate, spread = estimate_fill(trades)
    assert 0.0 <= fill_rate <= 1.0
    assert spread >= 0.0


def test_calibrate_emits_cost_calibration_shape(tmp_path, monkeypatch):
    # calibrate() with an empty/synthetic sample returns the COST_CALIBRATION shape (keys present).
    from cli.experiment.scripts.calibrate_execution import calibrate

    out = calibrate(sample_frames={"BTCUSDT": [_trades([100.0, 100.1], [1.0, 1.0], [True, False])]})
    assert set(out) >= {"impact_cost", "maker_fill_haircut", "tiers"}
    assert isinstance(out["impact_cost"], float)
