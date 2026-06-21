import numpy as np
import pandas as pd

from cli.experiment.strategies.regime import regime_exposure_series


def _close(values):
    idx = pd.date_range("2020-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype="float64")


def test_binary_full_above_ma_cash_below():
    # rising then falling around a short MA window
    up = list(range(1, 21))
    down = list(range(20, 0, -1))
    s = regime_exposure_series(_close(up + down), mode="binary", ma_window=5)
    # warmup (first <5) -> 1.0
    assert (s.iloc[:4] == 1.0).all()
    # deep in the uptrend -> close > MA -> 1.0; deep in downtrend -> 0.0
    assert s.iloc[18] == 1.0
    assert s.iloc[-2] == 0.0


def test_graded_has_chop_tier():
    flat = [100.0] * 30
    s = regime_exposure_series(_close(flat), mode="graded", ma_window=5, band=0.05, chop_exposure=0.5)
    # flat price == MA -> within band -> chop tier
    assert s.iloc[-1] == 0.5


def test_cross_uses_fast_vs_slow():
    up = list(range(1, 41))
    s = regime_exposure_series(_close(up), mode="cross", ma_window=20, ma_fast=5)
    # steady uptrend: fast MA > slow MA -> 1.0 once both windows are warm
    assert s.iloc[-1] == 1.0


def test_vol_target_scales_down_high_vol():
    rng = np.random.default_rng(0)
    calm = _close(100 + np.cumsum(rng.normal(0, 0.1, 400)))
    s_off = regime_exposure_series(calm, mode="binary", ma_window=5)
    s_on = regime_exposure_series(calm, mode="binary", ma_window=5, vol_target=0.0001, vol_lookback=20)
    # a tiny vol_target forces heavy downscaling vs off
    assert s_on.iloc[-1] < s_off.iloc[-1]
    assert (s_on >= 0).all() and (s_on <= 1).all()


def test_multiplier_bounded_unit_interval():
    s = regime_exposure_series(_close(list(range(1, 60))), mode="binary", ma_window=10)
    assert s.min() >= 0.0 and s.max() <= 1.0


def test_regime_get_risk_degree_scales_base_by_multiplier(monkeypatch):
    from cli.experiment.strategies import regime as rg

    # Avoid the qlib data query in __init__: stub _build_exposure to a fixed series.
    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    monkeypatch.setattr(
        rg.RegimeGatedTopkStrategy,
        "_build_exposure",
        lambda self: pd.Series([1.0, 0.0, 0.5], index=idx),
    )
    strat = rg.RegimeGatedTopkStrategy(topk=5, n_drop=1, signal=pd.Series(dtype="float64"), risk_degree=0.95)

    class _Cal:  # minimal trade_calendar stub
        def __init__(self, d):
            self._d = d

        def get_trade_step(self):
            return 0

        def get_step_time(self, step, shift=0):
            return (self._d, self._d)

    # qlib's `trade_calendar` is a read-only property; stub it at the class level.
    def _use(cal):
        monkeypatch.setattr(rg.RegimeGatedTopkStrategy, "trade_calendar", property(lambda self: cal), raising=False)

    _use(_Cal(idx[1]))  # risk-off date -> multiplier 0.0
    assert strat.get_risk_degree(0) == 0.0
    _use(_Cal(idx[0]))  # full
    assert strat.get_risk_degree(0) == 0.95
    _use(_Cal(idx[2]))  # chop -> 0.95 * 0.5
    assert abs(strat.get_risk_degree(0) - 0.475) < 1e-9
    # a date past the series -> carry forward the last value (0.5)
    _use(_Cal(pd.Timestamp("2025-06-01")))
    assert abs(strat.get_risk_degree(0) - 0.475) < 1e-9


def test_generate_trade_decision_pushes_gated_risk_degree_onto_attribute(monkeypatch):
    """Regression for the qlib inconsistency (see .tmp/qlib-bug-topkdropout-ignores-get-risk-degree.md):
    TopkDropoutStrategy sizes buys with the RAW ``self.risk_degree`` attribute, not ``get_risk_degree()``.
    So the regime gate is inert unless generate_trade_decision pushes the gated value onto the attribute
    before delegating. This test captures ``self.risk_degree`` at the moment qlib's sizing would read it.
    """
    from qlib.contrib.strategy.signal_strategy import TopkDropoutStrategy

    from cli.experiment.strategies import regime as rg

    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    monkeypatch.setattr(
        rg.RegimeGatedTopkStrategy,
        "_build_exposure",
        lambda self: pd.Series([1.0, 0.0, 0.5], index=idx),
    )
    strat = rg.RegimeGatedTopkStrategy(topk=5, n_drop=1, signal=pd.Series(dtype="float64"), risk_degree=0.95)

    class _Cal:
        def __init__(self, d):
            self._d = d

        def get_trade_step(self):
            return 0

        def get_step_time(self, step, shift=0):
            return (self._d, self._d)

    captured = {}

    def _fake_super(self, execute_result=None):
        captured["risk_degree"] = self.risk_degree  # what qlib's line-266 buy sizing would read
        return "DECISION"

    monkeypatch.setattr(TopkDropoutStrategy, "generate_trade_decision", _fake_super)

    def _use(cal):
        monkeypatch.setattr(rg.RegimeGatedTopkStrategy, "trade_calendar", property(lambda self: cal), raising=False)

    _use(_Cal(idx[1]))  # risk-off date -> gate 0.0 -> buys sized to cash
    assert strat.generate_trade_decision() == "DECISION"
    assert captured["risk_degree"] == 0.0

    _use(_Cal(idx[0]))  # full exposure -> base 0.95
    strat.generate_trade_decision()
    assert captured["risk_degree"] == 0.95

    _use(_Cal(idx[2]))  # chop 0.5 -> 0.95 * 0.5
    strat.generate_trade_decision()
    assert abs(captured["risk_degree"] - 0.475) < 1e-9
