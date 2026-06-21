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


def test_inverse_vol_weights_basics():
    import numpy as np
    import pandas as pd

    from cli.experiment.strategies.regime import inverse_vol_weights

    w = inverse_vol_weights(pd.Series({"A": 0.1, "B": 0.2, "C": 0.4}))
    assert abs(w.sum() - 1.0) < 1e-9
    assert w["A"] > w["B"] > w["C"]  # lower vol -> higher weight
    # non-finite / non-positive vols are dropped then renormalized
    w2 = inverse_vol_weights(pd.Series({"A": 0.1, "B": float("nan"), "C": 0.0, "D": 0.1}))
    assert abs(w2.sum() - 1.0) < 1e-9
    assert w2["B"] == 0.0 and w2["C"] == 0.0
    assert abs(w2["A"] - 0.5) < 1e-9 and abs(w2["D"] - 0.5) < 1e-9
    # all-bad -> equal-weight fallback
    w3 = inverse_vol_weights(pd.Series({"A": float("nan"), "B": 0.0}))
    assert abs(w3.sum() - 1.0) < 1e-9 and abs(w3["A"] - 0.5) < 1e-9


def test_volweight_strategy_no_lookahead(monkeypatch):
    """Cardinal: the weights for date t use the vol row STRICTLY BEFORE t, never t's own row."""
    import numpy as np
    import pandas as pd

    from cli.experiment.strategies import regime as rg

    s = object.__new__(rg.VolWeightedRegimeStrategy)
    s._base_risk_degree = 0.95
    dates = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"])
    # prior row (2025-01-02): A low vol, B high vol -> A should get the higher weight.
    # t's own row (2025-01-03): inverted (A high, B low) -> if used, weights would invert (look-ahead).
    s._vol_panel = pd.DataFrame({"A": [0.5, 0.1, 0.9], "B": [0.5, 0.9, 0.1]}, index=dates)
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=dates[2], trade_end_time=dates[2])
    # used the 2025-01-02 row (A=0.1 < B=0.9) -> A heavier. If it look-ahead-used 2025-01-03, A<B.
    assert w["A"] > w["B"], "look-ahead: weights must use the strictly-prior vol row"


def test_volweight_get_risk_degree_applies_regime(monkeypatch):
    import pandas as pd

    from cli.experiment.strategies import regime as rg

    s = object.__new__(rg.VolWeightedRegimeStrategy)
    s._base_risk_degree = 0.95
    idx = pd.date_range("2025-01-01", periods=2, freq="D")
    s._exposure = pd.Series([1.0, 0.0], index=idx)  # risk-on then risk-off

    class _Cal:
        def __init__(self, d):
            self._d = d

        def get_trade_step(self):
            return 0

        def get_step_time(self, step, shift=0):
            return (self._d, self._d)

    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _Cal(idx[1])), raising=False)
    assert s.get_risk_degree(0) == 0.0  # risk-off -> cash
    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _Cal(idx[0])), raising=False)
    assert s.get_risk_degree(0) == 0.95
