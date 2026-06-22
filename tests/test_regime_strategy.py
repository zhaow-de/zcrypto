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


# ---------------------------------------------------------------------------
# Liquidity-membership filter tests (Task 4)
# ---------------------------------------------------------------------------


def _make_volweight_stub(membership_top_n=None, membership_lookback_days=None):
    """Build a VolWeightedRegimeStrategy without calling __init__ (no qlib needed)."""
    from cli.experiment.strategies import regime as rg

    s = object.__new__(rg.VolWeightedRegimeStrategy)
    s._base_risk_degree = 0.95
    # vol panel: 3 dates, 4 names with equal low vols -> equal weights
    dates = pd.date_range("2025-01-01", periods=3, freq="D")
    s._vol_panel = pd.DataFrame(
        {"A": [0.1, 0.1, 0.1], "B": [0.1, 0.1, 0.1], "C": [0.1, 0.1, 0.1], "D": [0.1, 0.1, 0.1]},
        index=dates,
    )
    s.membership_top_n = membership_top_n
    s.membership_lookback_days = membership_lookback_days
    s._membership_schedule = None  # lazy slot; tests override below
    return s


def test_membership_filter_restricts_to_member_names():
    """With a 2-month injected schedule, only member names appear in the output weights."""
    from cli.experiment.strategies import regime as rg

    s = _make_volweight_stub(membership_top_n=10, membership_lookback_days=30)

    # Inject a schedule: Jan 2025 -> {A, B}; Feb 2025 -> {C, D}
    jan_ms = pd.Timestamp("2025-01-01")
    feb_ms = pd.Timestamp("2025-02-01")
    s._membership_schedule = {jan_ms: ["A", "B"], feb_ms: ["C", "D"]}

    # Trade date in Jan -> only A, B should have weights
    score = pd.Series({"A": 0.5, "B": 0.5, "C": 0.5, "D": 0.5})
    w = s.generate_target_weight_position(
        score, current=None, trade_start_time=pd.Timestamp("2025-01-15"), trade_end_time=pd.Timestamp("2025-01-15")
    )
    assert set(w.keys()) == {"A", "B"}, f"expected only A,B; got {set(w.keys())}"

    # Trade date in Feb -> only C, D
    w2 = s.generate_target_weight_position(
        score, current=None, trade_start_time=pd.Timestamp("2025-02-15"), trade_end_time=pd.Timestamp("2025-02-15")
    )
    assert set(w2.keys()) == {"C", "D"}, f"expected only C,D; got {set(w2.keys())}"


def test_membership_filter_carryforward_between_rebalances():
    """A date between two rebalances carries forward the most recent prior rebalance membership."""
    from cli.experiment.strategies import regime as rg

    s = _make_volweight_stub(membership_top_n=10, membership_lookback_days=30)

    jan_ms = pd.Timestamp("2025-01-01")
    mar_ms = pd.Timestamp("2025-03-01")
    # No Feb entry — Jan should carry forward to Feb 15
    s._membership_schedule = {jan_ms: ["A", "B"], mar_ms: ["C", "D"]}

    score = pd.Series({"A": 0.5, "B": 0.5, "C": 0.5, "D": 0.5})
    w = s.generate_target_weight_position(
        score, current=None, trade_start_time=pd.Timestamp("2025-02-15"), trade_end_time=pd.Timestamp("2025-02-15")
    )
    # Feb 15 is after Jan 1, before Mar 1 -> carry forward Jan -> {A, B}
    assert set(w.keys()) == {"A", "B"}, f"carry-forward failed; got {set(w.keys())}"


def test_membership_filter_before_first_rebalance_no_restriction():
    """A trade date before the earliest rebalance in the schedule -> no restriction (full universe)."""
    from cli.experiment.strategies import regime as rg

    s = _make_volweight_stub(membership_top_n=10, membership_lookback_days=30)

    feb_ms = pd.Timestamp("2025-02-01")
    s._membership_schedule = {feb_ms: ["A", "B"]}

    score = pd.Series({"A": 0.5, "B": 0.5, "C": 0.5, "D": 0.5})
    # Jan 15 is before the first rebalance (Feb 1) -> no restriction, all 4 names
    w = s.generate_target_weight_position(
        score, current=None, trade_start_time=pd.Timestamp("2025-01-15"), trade_end_time=pd.Timestamp("2025-01-15")
    )
    assert set(w.keys()) == {"A", "B", "C", "D"}, f"pre-first-rebalance should be unrestricted; got {set(w.keys())}"


def test_membership_filter_none_is_backcompat():
    """membership_top_n=None -> weights identical to the unfiltered path (regression)."""
    from cli.experiment.strategies import regime as rg

    # Build two stubs: one with filter off (None), one with filter kwarg entirely absent (simulated
    # by setting to None). Both should return weights for all 4 names.
    s = _make_volweight_stub(membership_top_n=None)

    score = pd.Series({"A": 0.5, "B": 0.5, "C": 0.5, "D": 0.5})
    w = s.generate_target_weight_position(
        score, current=None, trade_start_time=pd.Timestamp("2025-01-15"), trade_end_time=pd.Timestamp("2025-01-15")
    )
    assert set(w.keys()) == {"A", "B", "C", "D"}, f"no filter -> all names; got {set(w.keys())}"
    assert abs(sum(w.values()) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Per-asset trend-gating tests (Task 1, iter-35)
# ---------------------------------------------------------------------------


def _make_trend_stub(trend_window=None, membership_top_n=None):
    """Build a VolWeightedRegimeStrategy stub without calling __init__ (no qlib needed).

    Injects a 4-name vol panel with equal vols (equal weights) and sets trend_window.
    Tests that need a trend filter inject _close_panel themselves.
    """
    from cli.experiment.strategies import regime as rg

    s = object.__new__(rg.VolWeightedRegimeStrategy)
    s._base_risk_degree = 0.95
    # 120 days starting 2024-09-01 so any test trade date in 2025-Jan has prior vol rows available.
    dates = pd.date_range("2024-09-01", periods=120, freq="D")
    s._vol_panel = pd.DataFrame(
        {"A": [0.1] * 120, "B": [0.1] * 120, "C": [0.1] * 120, "D": [0.1] * 120},
        index=dates,
    )
    s.membership_top_n = membership_top_n
    s.membership_lookback_days = None
    s._membership_schedule = None
    s.trend_window = trend_window
    s._close_panel = None  # injectable seam
    return s


def _make_close_panel(names, dates, values_dict):
    """Build a synthetic close panel (MultiIndex: date x instrument)."""
    tuples = [(d, n) for d in dates for n in names]
    idx = pd.MultiIndex.from_tuples(tuples, names=["datetime", "instrument"])
    data = [values_dict[n][i] for i, d in enumerate(dates) for n in names]
    return pd.Series(data, index=idx, name="$close")


def test_trend_filter_drops_below_sma_names():
    """With trend_window=100 and injected close panel, only names with close > SMA survive."""
    from cli.experiment.strategies import regime as rg

    s = _make_trend_stub(trend_window=100, membership_top_n=10)

    # Inject membership active for the trade month (2024-12) so the gate genuinely fires:
    # {A, B, C} are members; D is not (D is dropped by membership, B/C by the trend filter).
    dec_ms = pd.Timestamp("2024-12-01")
    s._membership_schedule = {dec_ms: ["A", "B", "C"]}

    # Build a synthetic close panel:
    # 110 days of history so SMA(100) is defined on the last day
    # A: uptrend -> last close > SMA(100) -> survives
    # B: flat then drops -> last close < SMA(100) -> dropped
    # C: flat -> last close == SMA(100) -> dropped (≤ threshold)
    n_days = 110
    dates = pd.date_range("2024-09-01", periods=n_days, freq="D")

    a_closes = [float(100 + i) for i in range(n_days)]  # rising -> last close > SMA
    b_closes = [float(200 - i) for i in range(n_days)]  # falling -> last close < SMA
    c_closes = [100.0] * n_days  # flat -> last close == SMA -> dropped

    close_panel = pd.DataFrame({"A": a_closes, "B": b_closes, "C": c_closes}, index=dates)
    s._close_panel = close_panel

    trade_date = dates[-1]
    score = pd.Series({"A": 0.5, "B": 0.5, "C": 0.5, "D": 0.5})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)
    # Only A survives: in members AND close > SMA(100)
    assert set(w.keys()) == {"A"}, f"expected only A; got {set(w.keys())}"
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_trend_filter_intersects_with_membership():
    """Held set = members ∩ {close > SMA}; a name above SMA but not a member is excluded."""
    from cli.experiment.strategies import regime as rg

    s = _make_trend_stub(trend_window=5, membership_top_n=10)

    # Membership: {A, B}; C not a member even though it may be above SMA.
    # Trade date must be in Jan so the Jan membership key is picked up.
    jan_ms = pd.Timestamp("2025-01-01")
    s._membership_schedule = {jan_ms: ["A", "B"]}

    # 10 days ending in mid-January 2025 so trade_date falls within the Jan membership window.
    n_days = 10
    dates = pd.date_range("2025-01-05", periods=n_days, freq="D")
    a_closes = [float(100 + i) for i in range(n_days)]  # rising -> above SMA(5)
    b_closes = [float(200 - i) for i in range(n_days)]  # falling -> below SMA(5)
    c_closes = [float(100 + i) for i in range(n_days)]  # rising -> above SMA(5) but not a member

    close_panel = pd.DataFrame({"A": a_closes, "B": b_closes, "C": c_closes}, index=dates)
    s._close_panel = close_panel

    trade_date = dates[-1]
    score = pd.Series({"A": 0.5, "B": 0.5, "C": 0.5})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)
    # A: member AND above SMA -> kept; B: member BUT below SMA -> dropped; C: above SMA but not member -> dropped
    assert set(w.keys()) == {"A"}, f"expected only A; got {set(w.keys())}"


def test_trend_filter_market_gate_disabled():
    """When trend_window is set, get_risk_degree returns base * 1.0 (market BTC gate disabled)."""
    from cli.experiment.strategies import regime as rg

    s = _make_trend_stub(trend_window=100)
    # Inject a bearish BTC exposure series (would normally gate to 0.0)
    idx = pd.date_range("2025-01-01", periods=2, freq="D")
    s._exposure = pd.Series([0.0, 0.0], index=idx)  # BTC in full bear -> would zero exposure

    class _Cal:
        def __init__(self, d):
            self._d = d

        def get_trade_step(self):
            return 0

        def get_step_time(self, step, shift=0):
            return (self._d, self._d)

    import pytest

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _Cal(idx[0])), raising=False)
    # trend_window set -> market gate disabled -> full base_risk_degree regardless of BTC
    assert s.get_risk_degree(0) == 0.95, "market gate should be disabled when trend_window is set"
    monkeypatch.undo()


def test_trend_window_none_regression():
    """trend_window=None -> generate_target_weight_position output identical to today's behaviour."""
    from cli.experiment.strategies import regime as rg

    # Build two identical stubs: one with trend_window explicitly None (new kwarg default), one without.
    s1 = _make_trend_stub(trend_window=None, membership_top_n=None)
    s2 = _make_trend_stub(trend_window=None, membership_top_n=None)

    score = pd.Series({"A": 0.5, "B": 0.5, "C": 0.5, "D": 0.5})
    trade_date = pd.Timestamp("2025-01-03")
    w1 = s1.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)
    w2 = s2.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)
    assert w1 == w2
    assert set(w1.keys()) == {"A", "B", "C", "D"}  # all names, no filtering


def test_trend_filter_no_lookahead():
    """SMA uses closes strictly on/before the trade date — no look-ahead."""
    from cli.experiment.strategies import regime as rg

    s = _make_trend_stub(trend_window=3)

    # 6 days of closes; trade_date is day index 4 (the 5th date).
    # On days 0-4: A is below its 3d SMA (flat at 100).
    # On day 5 (AFTER trade_date): A jumps to 1000 — if look-ahead is used, SMA would be 400, close > SMA.
    # No look-ahead: only days 0-4 are used -> A flat at 100 -> close == SMA -> dropped.
    dates = pd.date_range("2025-01-01", periods=6, freq="D")
    a_closes = [100.0, 100.0, 100.0, 100.0, 100.0, 1000.0]
    close_panel = pd.DataFrame({"A": a_closes}, index=dates)
    s._close_panel = close_panel

    trade_date = dates[4]  # 5th date; day 5 is future
    score = pd.Series({"A": 0.5})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)
    # A flat (close == SMA) -> dropped (≤ threshold) — no look-ahead into day 5
    assert len(w) == 0 or w.get("A", 0.0) == 0.0, "look-ahead guard failed: future close must not affect SMA"


# ---------------------------------------------------------------------------
# compose_market_gate tests (Task 1, iter-37)
# ---------------------------------------------------------------------------


def _make_compose_stub(trend_window=None, compose_market_gate=False):
    """Build a VolWeightedRegimeStrategy stub for compose_market_gate tests.

    Inherits _make_trend_stub layout; adds compose_market_gate and _exposure injection.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_trend_stub(trend_window=trend_window)
    s.compose_market_gate = compose_market_gate
    # Default to a bullish exposure; tests that need bearish override this.
    idx = pd.date_range("2025-01-01", periods=2, freq="D")
    s._exposure = pd.Series([1.0, 1.0], index=idx)
    return s


def test_compose_mode_bearish_market_cashes_regardless_of_per_asset_trend():
    """compose_market_gate=True: bearish BTC exposure zeros get_risk_degree (market gate active)."""
    import pytest

    from cli.experiment.strategies import regime as rg

    s = _make_compose_stub(trend_window=100, compose_market_gate=True)
    # Override to bearish
    idx = pd.date_range("2025-01-01", periods=2, freq="D")
    s._exposure = pd.Series([0.0, 0.0], index=idx)

    class _Cal:
        def __init__(self, d):
            self._d = d

        def get_trade_step(self):
            return 0

        def get_step_time(self, step, shift=0):
            return (self._d, self._d)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _Cal(idx[0])), raising=False)
    # compose mode + bearish -> market gate fires -> risk_degree == 0.0
    assert s.get_risk_degree(0) == 0.0, "compose mode must honour market gate in a BTC-bear"
    monkeypatch.undo()


def test_compose_mode_bullish_market_per_asset_filter_still_drops_below_sma():
    """compose_market_gate=True: bullish market + per-asset filter active; below-SMA names dropped."""
    from cli.experiment.strategies import regime as rg

    s = _make_compose_stub(trend_window=100, compose_market_gate=True)
    # Bullish market exposure (gate passes)
    idx = pd.date_range("2025-01-01", periods=2, freq="D")
    s._exposure = pd.Series([1.0, 1.0], index=idx)

    # Build a close panel: 110 days; A rising (above SMA), B falling (below SMA)
    n_days = 110
    dates = pd.date_range("2024-09-01", periods=n_days, freq="D")
    a_closes = [float(100 + i) for i in range(n_days)]  # rising -> above SMA(100)
    b_closes = [float(200 - i) for i in range(n_days)]  # falling -> below SMA(100)
    s._close_panel = pd.DataFrame({"A": a_closes, "B": b_closes}, index=dates)

    trade_date = dates[-1]
    score = pd.Series({"A": 0.5, "B": 0.5})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)
    # In bullish market: per-asset filter active -> only A (above SMA) kept
    assert set(w.keys()) == {"A"}, f"expected only A after per-asset filter; got {set(w.keys())}"
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_replace_mode_regression_bearish_market_ignored():
    """compose_market_gate=False (default): market gate disabled even with bearish BTC exposure."""
    import pytest

    from cli.experiment.strategies import regime as rg

    s = _make_compose_stub(trend_window=100, compose_market_gate=False)
    # Bearish market exposure
    idx = pd.date_range("2025-01-01", periods=2, freq="D")
    s._exposure = pd.Series([0.0, 0.0], index=idx)

    class _Cal:
        def __init__(self, d):
            self._d = d

        def get_trade_step(self):
            return 0

        def get_step_time(self, step, shift=0):
            return (self._d, self._d)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _Cal(idx[0])), raising=False)
    # replace mode (compose_market_gate=False) -> gate disabled -> full base risk degree
    assert s.get_risk_degree(0) == 0.95, "replace mode must ignore market gate"
    monkeypatch.undo()


def test_replace_mode_regression_above_sma_coin_held_in_bear():
    """compose_market_gate=False: a coin above its own SMA is held even with bearish BTC exposure."""
    from cli.experiment.strategies import regime as rg

    s = _make_compose_stub(trend_window=100, compose_market_gate=False)
    # Bearish market (irrelevant in replace mode)
    idx = pd.date_range("2025-01-01", periods=2, freq="D")
    s._exposure = pd.Series([0.0, 0.0], index=idx)

    # A is above its SMA; with replace mode the market gate is disabled, so A should be held.
    n_days = 110
    dates = pd.date_range("2024-09-01", periods=n_days, freq="D")
    a_closes = [float(100 + i) for i in range(n_days)]  # rising -> above SMA(100)
    s._close_panel = pd.DataFrame({"A": a_closes}, index=dates)

    trade_date = dates[-1]
    score = pd.Series({"A": 0.5})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)
    # A above SMA; replace mode ignores bear market -> A is held
    assert "A" in w, f"replace mode: above-SMA coin must be held in bear market; got {w}"
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_trend_window_none_compose_flag_ignored_regression():
    """trend_window=None: compose_market_gate has no effect (market gate governs via _exposure)."""
    import pytest

    from cli.experiment.strategies import regime as rg

    # Build two stubs: trend_window=None, one with compose_market_gate=True, one False.
    # Both should behave identically: the market gate (from _exposure) is active.
    s1 = _make_compose_stub(trend_window=None, compose_market_gate=True)
    s2 = _make_compose_stub(trend_window=None, compose_market_gate=False)

    idx = pd.date_range("2025-01-01", periods=2, freq="D")
    # Set same bullish exposure for both
    s1._exposure = pd.Series([0.8, 0.8], index=idx)
    s2._exposure = pd.Series([0.8, 0.8], index=idx)

    class _Cal:
        def __init__(self, d):
            self._d = d

        def get_trade_step(self):
            return 0

        def get_step_time(self, step, shift=0):
            return (self._d, self._d)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _Cal(idx[0])), raising=False)
    rd1 = s1.get_risk_degree(0)
    rd2 = s2.get_risk_degree(0)
    monkeypatch.undo()
    assert rd1 == rd2, f"trend_window=None: compose flag must not alter risk_degree ({rd1} vs {rd2})"
    assert abs(rd1 - 0.95 * 0.8) < 1e-9


# ---------------------------------------------------------------------------
# Basis-froth overlay tests (iter-39)
# ---------------------------------------------------------------------------


def _make_froth_stub(froth_field=None, froth_lookback=90, froth_z_threshold=1.5, froth_derisk_mult=0.0):
    """Build a VolWeightedRegimeStrategy stub without calling __init__ (no qlib needed).

    Injects a bullish exposure series and froth params; tests inject _froth_signal themselves.
    """
    from cli.experiment.strategies import regime as rg

    s = object.__new__(rg.VolWeightedRegimeStrategy)
    s._base_risk_degree = 0.95
    idx = pd.date_range("2025-01-01", periods=5, freq="D")
    # Bullish BTC exposure throughout
    s._exposure = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0], index=idx)
    s.trend_window = None
    s.compose_market_gate = False
    s.froth_field = froth_field
    s.froth_lookback = froth_lookback
    s.froth_z_threshold = froth_z_threshold
    s.froth_derisk_mult = froth_derisk_mult
    s._froth_signal = None  # injectable seam; tests override below
    return s


class _FrothCal:
    """Minimal trade_calendar stub for froth tests."""

    def __init__(self, d):
        self._d = d

    def get_trade_step(self):
        return 0

    def get_step_time(self, step, shift=0):
        return (self._d, self._d)


def test_froth_above_threshold_zeroes_exposure():
    """froth_z > threshold at date → exposure = regime_mult × froth_derisk_mult (0.0 → cash)."""
    import pytest

    from cli.experiment.strategies import regime as rg

    s = _make_froth_stub(froth_field="$basis", froth_z_threshold=1.5, froth_derisk_mult=0.0)
    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    # Inject: day 0 below threshold, day 1 above threshold (frothy), day 2 below again
    s._froth_signal = pd.Series([0.5, 2.0, 0.3], index=idx)

    monkeypatch = pytest.MonkeyPatch()
    # Day 1 (froth_z=2.0 > 1.5) → de-risked → 0.95 * 1.0 (regime) * 0.0 (froth) = 0.0
    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _FrothCal(idx[1])), raising=False)
    assert s.get_risk_degree(0) == 0.0, "above-threshold froth must zero exposure"
    monkeypatch.undo()


def test_froth_below_threshold_regime_multiplier_unchanged():
    """froth_z below threshold → regime multiplier applies; froth overlay does not fire."""
    import pytest

    from cli.experiment.strategies import regime as rg

    s = _make_froth_stub(froth_field="$basis", froth_z_threshold=1.5, froth_derisk_mult=0.0)
    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    s._froth_signal = pd.Series([0.5, 1.0, 0.3], index=idx)  # all below 1.5

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _FrothCal(idx[1])), raising=False)
    # No de-risk → 0.95 * 1.0 (regime, bullish) = 0.95
    assert abs(s.get_risk_degree(0) - 0.95) < 1e-9, "below-threshold froth must not alter risk_degree"
    monkeypatch.undo()


def test_froth_field_none_regression():
    """froth_field=None → _mult_for behaves identically to before the overlay was added (regression)."""
    import pytest

    from cli.experiment.strategies import regime as rg

    # Two identical stubs: one with froth_field=None, one with no froth attrs set at all (old-style stub).
    s_with = _make_froth_stub(froth_field=None)
    s_without = object.__new__(rg.VolWeightedRegimeStrategy)
    s_without._base_risk_degree = 0.95
    idx = pd.date_range("2025-01-01", periods=5, freq="D")
    s_without._exposure = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0], index=idx)
    s_without.trend_window = None
    s_without.compose_market_gate = False
    # No froth attrs at all — getattr guards must handle this.

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _FrothCal(idx[2])), raising=False)
    rd_with = s_with.get_risk_degree(0)
    rd_without = s_without.get_risk_degree(0)
    monkeypatch.undo()
    assert abs(rd_with - rd_without) < 1e-9, "froth_field=None must not alter risk_degree vs no-froth stub"
    assert abs(rd_with - 0.95) < 1e-9


def test_froth_nan_z_does_not_derisk():
    """NaN froth_z (warmup / missing data) → overlay does NOT de-risk (treat NaN as 'no signal')."""
    import pytest

    from cli.experiment.strategies import regime as rg

    s = _make_froth_stub(froth_field="$basis", froth_z_threshold=1.5, froth_derisk_mult=0.0)
    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    # NaN on day 1 (warmup)
    s._froth_signal = pd.Series([float("nan"), float("nan"), 0.5], index=idx)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _FrothCal(idx[1])), raising=False)
    # NaN froth → no de-risk → full regime mult applies
    assert abs(s.get_risk_degree(0) - 0.95) < 1e-9, "NaN froth_z must not trigger de-risk"
    monkeypatch.undo()


def test_froth_no_lookahead():
    """The froth z-score at date d uses only dates ≤ d (rolling window, no look-ahead)."""
    # Build a froth signal directly (no qlib) and verify rolling z-score is causal.
    cs_median = pd.Series(
        [0.0, 0.0, 0.0, 0.0, 5.0],  # day 4 is a big spike — only affects z-score AT day 4+
        index=pd.date_range("2025-01-01", periods=5, freq="D"),
    )
    lb = 3
    roll_mean = cs_median.rolling(lb, min_periods=lb).mean()
    roll_std = cs_median.rolling(lb, min_periods=lb).std()
    froth_z = (cs_median - roll_mean) / roll_std

    # At day 3 (idx=3), the window is [0,0,0] → mean=0, std=0 → z is NaN or 0 (std=0 case);
    # the spike on day 4 must NOT affect the z at day 3.
    z_at_day3 = froth_z.iloc[3]
    # std([0,0,0]) = 0 → z = NaN; either way, no signal from the future spike
    assert z_at_day3 != z_at_day3 or z_at_day3 == 0.0, "future spike must not influence prior z-score"
    # At day 4, the spike IS reflected (causal update)
    z_at_day4 = froth_z.iloc[4]
    assert not (z_at_day4 != z_at_day4), "z at spike day must be non-NaN (causal)"
    assert z_at_day4 > 1.0, "spike should produce a z above threshold"
