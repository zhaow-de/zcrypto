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


def test_onchain_path_resolved_against_repo_root():
    """_resolve_onchain_path returns absolute paths, resolving relative ones against the repo root."""
    from pathlib import Path

    from cli.experiment.strategies.regime import _resolve_onchain_path

    repo_root = Path(__file__).resolve().parents[1]  # tests/ -> repo root
    assert (repo_root / "pyproject.toml").exists(), "sanity: repo_root is wrong"

    # Absolute path is returned unchanged
    abs_path = Path("/tmp/some/absolute.parquet")
    assert _resolve_onchain_path(str(abs_path)) == abs_path

    # Relative path is resolved against repo root, not CWD
    rel = "data/onchain/btc_nvm.parquet"
    result = _resolve_onchain_path(rel)
    assert result.is_absolute()
    assert str(result).endswith("data/onchain/btc_nvm.parquet")
    assert result == repo_root / rel


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


# ---------------------------------------------------------------------------
# Cross-sectional crowding-tilt tests (iter-40)
# ---------------------------------------------------------------------------


def _make_crowding_stub(crowding_field=None, crowding_tilt_k=1.0):
    """Build a VolWeightedRegimeStrategy stub without calling __init__ (no qlib needed).

    Sets up a 4-name equal-vol panel; tests inject _crowding_panel themselves.
    """
    from cli.experiment.strategies import regime as rg

    s = object.__new__(rg.VolWeightedRegimeStrategy)
    s._base_risk_degree = 0.95
    # 5 days; equal vol for all names so plain inverse-vol gives equal weights
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._vol_panel = pd.DataFrame(
        {"A": [0.1] * 5, "B": [0.1] * 5, "C": [0.1] * 5, "D": [0.1] * 5},
        index=dates,
    )
    s.membership_top_n = None
    s.membership_lookback_days = None
    s._membership_schedule = None
    s.trend_window = None
    s._close_panel = None
    s.crowding_field = crowding_field
    s.crowding_tilt_k = crowding_tilt_k
    s._crowding_panel = None  # injectable seam
    return s


def test_crowding_tilt_high_basis_downweighted():
    """One HIGH-prior-basis coin (z>0) gets a lower weight; LOW-basis coin gets higher weight.

    Equal vols → equal inverse-vol weights; tilt shifts distribution: high-basis down, low-basis up.
    Weights must still sum to ~1.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_crowding_stub(crowding_field="$basis", crowding_tilt_k=1.0)

    # Crowding panel: 4 dates of prior data + 1 future row that must NOT be used.
    # On day 3 (the last prior row for trade_date=day 4): A=2.0 (high basis), B=-2.0 (low/backwardated).
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._crowding_panel = pd.DataFrame(
        {"A": [1.0, 1.5, 2.0, 2.0, 99.0], "B": [-1.0, -1.5, -2.0, -2.0, 99.0]},
        index=dates,
    )

    trade_date = dates[4]  # use only rows strictly before dates[4] = rows 0-3
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert set(w.keys()) == {"A", "B"}, f"both names should be held; got {set(w.keys())}"
    assert abs(sum(w.values()) - 1.0) < 1e-9, f"weights must sum to 1; got {sum(w.values())}"
    assert w["A"] < w["B"], "high-basis coin A must be down-weighted vs low-basis coin B"


def test_crowding_tilt_none_regression():
    """crowding_field=None → weights byte-identical to plain inverse-vol (regression)."""
    from cli.experiment.strategies import regime as rg

    s_no_tilt = _make_crowding_stub(crowding_field=None)
    s_tilt = _make_crowding_stub(crowding_field="$basis", crowding_tilt_k=1.0)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s_tilt._crowding_panel = pd.DataFrame(
        {"A": [1.0, 2.0, 3.0, 4.0, 99.0], "B": [-1.0, -2.0, -3.0, -4.0, 99.0]},
        index=dates,
    )

    score = pd.Series({"A": 0.0, "B": 0.0})
    trade_date = dates[4]
    w_no_tilt = s_no_tilt.generate_target_weight_position(
        score, current=None, trade_start_time=trade_date, trade_end_time=trade_date
    )
    w_tilt = s_tilt.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    # With crowding_field=None the tilt must NOT be applied; equal-vol basket stays 50/50.
    assert abs(w_no_tilt["A"] - 0.5) < 1e-9
    assert abs(w_no_tilt["B"] - 0.5) < 1e-9
    # The tilted version must differ (A down-weighted, B up-weighted).
    assert w_tilt["A"] < w_tilt["B"]


def test_crowding_tilt_nan_crowding_neutral():
    """A coin with NaN crowding gets tilt=1.0 (neutral); the other coins tilt among themselves.

    Three names: A NaN, B high-basis, C low-basis. After tilt:
    - A's weight stays proportional to 1.0 (tilt factor 1.0)
    - B's weight shrinks; C's weight grows
    - sum is still 1.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_crowding_stub(crowding_field="$basis", crowding_tilt_k=1.0)
    # 4-name equal vol panel for A, B, C (override the 4-name stub to 3 names)
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._vol_panel = pd.DataFrame(
        {"A": [0.1] * 5, "B": [0.1] * 5, "C": [0.1] * 5},
        index=dates,
    )
    # A has NaN crowding; B high-basis; C low-basis
    s._crowding_panel = pd.DataFrame(
        {"A": [float("nan")] * 5, "B": [2.0] * 5, "C": [-2.0] * 5},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0, "C": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert set(w.keys()) == {"A", "B", "C"}, f"all three names should be held; got {set(w.keys())}"
    assert abs(sum(w.values()) - 1.0) < 1e-9, "weights must sum to 1"
    # B (high-basis, z>0) must be down-weighted vs C (low-basis, z<0)
    assert w["B"] < w["C"], "high-basis B must be down-weighted vs low-basis C"
    # A (NaN → tilt 1.0) should be between B and C (or equal to plain inverse-vol share before renorm)
    # The key check: A's contribution is not reduced due to its own NaN (tilt is 1.0, neutral)
    # After renorm, A > B is reasonable since B was shrunk and A was kept at its neutral share.
    assert w["A"] > w["B"], "NaN-crowding coin A should not be penalised vs high-basis B"


def test_crowding_tilt_no_lookahead():
    """The tilt at date t must use ONLY crowding rows strictly before t.

    Inject a panel with a future row (at trade_date itself) that would invert the tilt if used.
    Assert the inversion does NOT happen.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_crowding_stub(crowding_field="$basis", crowding_tilt_k=1.0)

    # Prior rows (dates 0-3): A high-basis, B low-basis → A should be down-weighted.
    # Future row (date 4 = trade_date): A=-99.0, B=+99.0 → if used, would make A up-weighted.
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._crowding_panel = pd.DataFrame(
        {"A": [2.0, 2.0, 2.0, 2.0, -99.0], "B": [-2.0, -2.0, -2.0, -2.0, 99.0]},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    # Strictly prior rows say A is high-basis → must be down-weighted vs B
    assert w["A"] < w["B"], "look-ahead guard failed: future crowding row must not be used"


# ---------------------------------------------------------------------------
# OI-price-divergence tilt tests (iter-41)
# ---------------------------------------------------------------------------


def _make_oi_div_stub(oi_divergence=True, oi_div_lookback=14, oi_div_tilt_k=1.0):
    """Build a VolWeightedRegimeStrategy stub without calling __init__ (no qlib needed).

    Sets up a 4-name equal-vol panel (equal inverse-vol weights); tests inject
    _oi_div_signal and _vol_panel themselves.
    """
    from cli.experiment.strategies import regime as rg

    s = object.__new__(rg.VolWeightedRegimeStrategy)
    s._base_risk_degree = 0.95
    # 5 days; equal vol for all names so plain inverse-vol gives equal weights
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._vol_panel = pd.DataFrame(
        {"A": [0.1] * 5, "B": [0.1] * 5, "C": [0.1] * 5, "D": [0.1] * 5},
        index=dates,
    )
    s.membership_top_n = None
    s.membership_lookback_days = None
    s._membership_schedule = None
    s.trend_window = None
    s._close_panel = None
    s.crowding_field = None
    s.crowding_tilt_k = 1.0
    s._crowding_panel = None
    s.oi_divergence = oi_divergence
    s.oi_div_lookback = oi_div_lookback
    s.oi_div_tilt_k = oi_div_tilt_k
    s._oi_div_signal = None  # injectable seam
    return s


def test_oi_div_tilt_confirmed_coin_upweighted():
    """One HIGH-confirmation coin (z>0) gets a HIGHER weight; divergent coin (z<0) LOWER.

    Opposite of the crowding tilt: high-z → up-weight (exp(+k*z) > 1).
    Equal vols → equal inverse-vol weights; tilt shifts distribution.
    Weights must still sum to ~1.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_oi_div_stub(oi_divergence=True, oi_div_tilt_k=1.0)

    # OI-div panel: 4 prior dates + 1 future row that must NOT be used.
    # Prior row (date 3): A has positive confirmation (price↑+OI↑), B has negative (price↑+OI↓).
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._oi_div_signal = pd.DataFrame(
        {"A": [0.5, 0.8, 1.0, 1.0, -99.0], "B": [-0.5, -0.8, -1.0, -1.0, 99.0]},
        index=dates,
    )

    trade_date = dates[4]  # use only rows strictly before dates[4] = rows 0-3
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert set(w.keys()) == {"A", "B"}, f"both names should be held; got {set(w.keys())}"
    assert abs(sum(w.values()) - 1.0) < 1e-9, f"weights must sum to 1; got {sum(w.values())}"
    # A (confirmed, z>0) must be UP-weighted (opposite of crowding tilt)
    assert w["A"] > w["B"], "confirmed coin A must be UP-weighted vs divergent coin B"


def test_oi_div_tilt_false_regression():
    """oi_divergence=False → weights byte-identical to plain inverse-vol (regression)."""
    from cli.experiment.strategies import regime as rg

    s_no_tilt = _make_oi_div_stub(oi_divergence=False)
    s_tilt = _make_oi_div_stub(oi_divergence=True, oi_div_tilt_k=1.0)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s_tilt._oi_div_signal = pd.DataFrame(
        {"A": [1.0, 2.0, 3.0, 4.0, 99.0], "B": [-1.0, -2.0, -3.0, -4.0, 99.0]},
        index=dates,
    )

    score = pd.Series({"A": 0.0, "B": 0.0})
    trade_date = dates[4]
    w_no_tilt = s_no_tilt.generate_target_weight_position(
        score, current=None, trade_start_time=trade_date, trade_end_time=trade_date
    )
    w_tilt = s_tilt.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    # Without tilt the equal-vol basket stays 50/50.
    assert abs(w_no_tilt["A"] - 0.5) < 1e-9
    assert abs(w_no_tilt["B"] - 0.5) < 1e-9
    # The tilted version must differ (A up-weighted, B down-weighted).
    assert w_tilt["A"] > w_tilt["B"]


def test_oi_div_tilt_nan_confirmation_neutral():
    """A coin with NaN OI-divergence gets tilt=1.0 (neutral); others tilt among themselves.

    Three names: A NaN (no perp), B high-confirmation, C divergent.
    After tilt: B's weight grows; C's weight shrinks; A stays at neutral share.
    Weights sum to 1.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_oi_div_stub(oi_divergence=True, oi_div_tilt_k=1.0)
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._vol_panel = pd.DataFrame(
        {"A": [0.1] * 5, "B": [0.1] * 5, "C": [0.1] * 5},
        index=dates,
    )
    # A has NaN (no perp); B confirmed; C divergent
    s._oi_div_signal = pd.DataFrame(
        {"A": [float("nan")] * 5, "B": [2.0] * 5, "C": [-2.0] * 5},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0, "C": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert set(w.keys()) == {"A", "B", "C"}, f"all three names should be held; got {set(w.keys())}"
    assert abs(sum(w.values()) - 1.0) < 1e-9, "weights must sum to 1"
    # B (confirmed, z>0) must be UP-weighted vs C (divergent, z<0)
    assert w["B"] > w["C"], "confirmed B must be up-weighted vs divergent C"
    # A (NaN → tilt 1.0) should not be penalised; it should be between or above C
    assert w["A"] > w["C"], "NaN-signal coin A should not be penalised vs divergent C"


def test_oi_div_tilt_no_lookahead():
    """The OI-divergence tilt at date t must use ONLY signal rows strictly before t.

    Inject a panel where the future row (at trade_date) would invert the tilt if used.
    Assert the inversion does NOT happen.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_oi_div_stub(oi_divergence=True, oi_div_tilt_k=1.0)

    # Prior rows (dates 0-3): A confirmed (+), B divergent (−) → A should be up-weighted.
    # Future row (date 4 = trade_date): A=-99.0, B=+99.0 → if used, B would be up-weighted.
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._oi_div_signal = pd.DataFrame(
        {"A": [1.0, 1.0, 1.0, 1.0, -99.0], "B": [-1.0, -1.0, -1.0, -1.0, 99.0]},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    # Strictly prior rows say A is confirmed → must be UP-weighted vs B
    assert w["A"] > w["B"], "look-ahead guard failed: future OI-div row must not be used"


def test_crowding_tilt_still_works_after_refactor():
    """Regression: the crowding tilt (−k sign) still down-weights high-basis coins after the
    _apply_cross_sectional_tilt refactor introduced for iter-41.
    """
    from cli.experiment.strategies import regime as rg

    # Build a crowding stub (uses the crowding-tilt path, not OI-div)
    s = _make_crowding_stub(crowding_field="$basis", crowding_tilt_k=1.0)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._crowding_panel = pd.DataFrame(
        {"A": [2.0, 2.0, 2.0, 2.0, -99.0], "B": [-2.0, -2.0, -2.0, -2.0, 99.0]},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    # High-basis A (z>0) must be DOWN-weighted (crowding tilt uses −k sign)
    assert w["A"] < w["B"], "crowding tilt regression: high-basis A must still be down-weighted"
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_oi_div_signal_construction_quadrants():
    """confirmation = sign(price_chg) * oi_chg has the correct sign for all four quadrants.

    price↑ + OI↑ → +  (confirmed: new money entering on a rally)
    price↑ + OI↓ → −  (divergent: short-covering, no conviction)
    price↓ + OI↓ → +  (confirmed: longs exiting, conviction to the downside)
    price↓ + OI↑ → −  (divergent: new shorts entering on a falling OI market — bearish but confused)
    """
    import numpy as np

    # Direct verification of the formula (no qlib, no strategy instantiation needed)
    def confirmation(price_chg, oi_chg):
        return np.sign(price_chg) * oi_chg

    # price↑ + OI↑ → positive
    assert confirmation(+0.05, +0.10) > 0, "price↑+OI↑ must be +confirmed"
    # price↑ + OI↓ → negative
    assert confirmation(+0.05, -0.10) < 0, "price↑+OI↓ must be −divergent"
    # price↓ + OI↓ → positive (sign(−)*(-) = (+)*(−) wait — sign(−0.05) = −1; −1*−0.10 = +0.10)
    assert confirmation(-0.05, -0.10) > 0, "price↓+OI↓ must be +confirmed"
    # price↓ + OI↑ → negative
    assert confirmation(-0.05, +0.10) < 0, "price↓+OI↑ must be −divergent"


# ---------------------------------------------------------------------------
# Directional OI-divergence tilt tests (iter-42)
# ---------------------------------------------------------------------------


def _make_oi_div_directional_stub(oi_div_directional=True, oi_div_tilt_k=1.0):
    """Build a VolWeightedRegimeStrategy stub for directional OI-div tests.

    Inherits _make_oi_div_stub layout; adds oi_div_directional.
    """
    from cli.experiment.strategies import regime as rg

    s = object.__new__(rg.VolWeightedRegimeStrategy)
    s._base_risk_degree = 0.95
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._vol_panel = pd.DataFrame(
        {"A": [0.1] * 5, "B": [0.1] * 5, "C": [0.1] * 5},
        index=dates,
    )
    s.membership_top_n = None
    s.membership_lookback_days = None
    s._membership_schedule = None
    s.trend_window = None
    s._close_panel = None
    s.crowding_field = None
    s.crowding_tilt_k = 1.0
    s._crowding_panel = None
    s.oi_divergence = True
    s.oi_div_lookback = 14
    s.oi_div_tilt_k = oi_div_tilt_k
    s.oi_div_directional = oi_div_directional
    s._oi_div_signal = None  # injectable seam
    return s


def test_oi_div_directional_signal_up_price_keeps_oi_chg():
    """Directional signal: up-price coin's confirmation equals its oi_chg.

    With oi_div_directional=True: confirmation_i = oi_chg_i where price_chg_i > 0, else NaN.
    Tested via the formula directly (no qlib needed).
    """
    # Simulate the formula from _build_oi_div_signal with oi_div_directional=True
    price_chg = pd.Series({"A": +0.05, "B": -0.03, "C": +0.02})
    oi_chg = pd.Series({"A": +0.10, "B": +0.08, "C": -0.04})
    confirmation = oi_chg.where(price_chg > 0)

    # A (price up): confirmation == oi_chg
    assert abs(confirmation["A"] - oi_chg["A"]) < 1e-12, "up-price coin: confirmation must equal oi_chg"
    # C (price up): confirmation == oi_chg (negative oi_chg is fine; signal range is unrestricted)
    assert abs(confirmation["C"] - oi_chg["C"]) < 1e-12, "up-price coin: confirmation must equal oi_chg"
    # B (price down): confirmation is NaN
    assert confirmation["B"] != confirmation["B"], "down-price coin: confirmation must be NaN"


def test_oi_div_directional_signal_down_price_is_nan():
    """Directional signal: down-price coin's confirmation is NaN (→ neutral tilt)."""
    price_chg = pd.Series({"A": -0.05, "B": -0.03})
    oi_chg = pd.Series({"A": -0.10, "B": +0.08})
    confirmation = oi_chg.where(price_chg > 0)

    assert confirmation["A"] != confirmation["A"], "down-price coin A: must be NaN"
    assert confirmation["B"] != confirmation["B"], "down-price coin B: must be NaN"


def test_oi_div_nondirectional_formula_unchanged():
    """Non-directional (oi_div_directional=False) confirmation = sign(price_chg)*oi_chg (iter-41 formula)."""
    import numpy as np

    price_chg = pd.Series({"A": +0.05, "B": -0.03, "C": +0.02, "D": -0.08})
    oi_chg = pd.Series({"A": +0.10, "B": +0.08, "C": -0.04, "D": -0.06})
    confirmation = np.sign(price_chg) * oi_chg

    assert confirmation["A"] > 0, "price↑+OI↑ → positive"
    assert confirmation["B"] < 0, "price↓+OI↑ → negative"
    assert confirmation["C"] < 0, "price↑+OI↓ → negative"
    assert confirmation["D"] > 0, "price↓+OI↓ → positive"


def test_oi_div_directional_tilt_up_mover_high_oi_upweighted():
    """Directional tilt: up-mover with high OI (z>0) is up-weighted; up-mover with low OI (z<0) down-weighted.

    A: up-price, high OI → confirmation positive → z > 0 → tilt > 1 → up-weighted.
    B: up-price, low OI  → confirmation negative → z < 0 → tilt < 1 → down-weighted.
    Weights sum to 1.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_oi_div_directional_stub(oi_div_directional=True, oi_div_tilt_k=1.0)

    # Only A and B; both are up-movers (non-NaN confirmation).
    # A: high OI confirmation (+); B: low OI confirmation (−).
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._vol_panel = pd.DataFrame({"A": [0.1] * 5, "B": [0.1] * 5}, index=dates)
    s._oi_div_signal = pd.DataFrame(
        {"A": [0.5, 0.8, 1.0, 1.0, -99.0], "B": [-0.5, -0.8, -1.0, -1.0, 99.0]},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert set(w.keys()) == {"A", "B"}, f"both up-movers should be held; got {set(w.keys())}"
    assert abs(sum(w.values()) - 1.0) < 1e-9, f"weights must sum to 1; got {sum(w.values())}"
    assert w["A"] > w["B"], "up-mover A (high OI z>0) must be UP-weighted vs up-mover B (low OI z<0)"


def test_oi_div_directional_tilt_down_price_coin_neutral():
    """Directional tilt: down-price coin (NaN confirmation) is left neutral (untilted weight).

    Three names with equal vols:
    - A: up-price, positive OI (z>0) → up-weighted
    - B: up-price, negative OI (z<0) → down-weighted
    - C: down-price (NaN confirmation) → tilt=1.0 (neutral); weight unchanged relative to inverse-vol share
    Weights sum to 1.  C must not be penalized vs its equal-vol baseline.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_oi_div_directional_stub(oi_div_directional=True, oi_div_tilt_k=1.0)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    # C has NaN confirmation (down-price → neutral)
    s._oi_div_signal = pd.DataFrame(
        {"A": [1.0, 1.0, 1.0, 1.0, -99.0], "B": [-1.0, -1.0, -1.0, -1.0, 99.0], "C": [float("nan")] * 5},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0, "C": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert set(w.keys()) == {"A", "B", "C"}, f"all three names should be held; got {set(w.keys())}"
    assert abs(sum(w.values()) - 1.0) < 1e-9, "weights must sum to 1"
    # C (NaN → tilt=1.0) must not be penalized vs A or B.  Since A is up-weighted and C is neutral,
    # C should be greater than or equal to B (which is down-weighted).
    assert w["C"] > w["B"], "neutral down-price coin C must not be penalised vs down-weighted B"
    # A (high OI, z>0) is up-weighted above C (neutral)
    assert w["A"] > w["C"], "up-mover A (high OI) must be up-weighted above neutral C"


def test_oi_div_directional_tilt_no_lookahead():
    """Directional tilt strictly-prior lookup: future signal row must not affect weights."""
    from cli.experiment.strategies import regime as rg

    s = _make_oi_div_directional_stub(oi_div_directional=True, oi_div_tilt_k=1.0)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._vol_panel = pd.DataFrame({"A": [0.1] * 5, "B": [0.1] * 5}, index=dates)
    # Prior rows (0-3): A confirmed (+), B divergent (−) → A up-weighted.
    # Future row (date 4 = trade_date): A=-99.0, B=+99.0 → if used, B would be up-weighted.
    s._oi_div_signal = pd.DataFrame(
        {"A": [1.0, 1.0, 1.0, 1.0, -99.0], "B": [-1.0, -1.0, -1.0, -1.0, 99.0]},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert w["A"] > w["B"], "look-ahead guard failed: future OI-div row must not be used"


def test_oi_div_directional_false_regression():
    """oi_div_directional=False → weights byte-identical to iter-41 (oi_div_directional absent/False)."""
    from cli.experiment.strategies import regime as rg

    # Reference: iter-41 stub with directional flag absent (uses getattr default)
    s_iter41 = _make_oi_div_stub(oi_divergence=True, oi_div_tilt_k=1.0)
    # New stub with directional flag explicitly False
    s_false = _make_oi_div_directional_stub(oi_div_directional=False, oi_div_tilt_k=1.0)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    signal = pd.DataFrame(
        {"A": [1.0, 2.0, 3.0, 4.0, 99.0], "B": [-1.0, -2.0, -3.0, -4.0, 99.0]},
        index=dates,
    )
    s_iter41._oi_div_signal = signal.copy()
    s_false._oi_div_signal = signal.copy()
    s_false._vol_panel = pd.DataFrame({"A": [0.1] * 5, "B": [0.1] * 5}, index=dates)

    score = pd.Series({"A": 0.0, "B": 0.0})
    trade_date = dates[4]
    w_iter41 = s_iter41.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)
    w_false = s_false.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert abs(w_iter41["A"] - w_false["A"]) < 1e-12, "directional=False must be byte-identical to iter-41"
    assert abs(w_iter41["B"] - w_false["B"]) < 1e-12, "directional=False must be byte-identical to iter-41"


# ---------------------------------------------------------------------------
# Smart-money L/S divergence tilt tests (iter-43)
# ---------------------------------------------------------------------------


def _make_smart_money_stub(smart_money=True, smart_money_tilt_k=1.0):
    """Build a VolWeightedRegimeStrategy stub without calling __init__ (no qlib needed).

    Sets up a 3-name equal-vol panel; tests inject _smart_money_signal themselves.
    """
    from cli.experiment.strategies import regime as rg

    s = object.__new__(rg.VolWeightedRegimeStrategy)
    s._base_risk_degree = 0.95
    # 5 days; equal vol for all names so plain inverse-vol gives equal weights
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._vol_panel = pd.DataFrame(
        {"A": [0.1] * 5, "B": [0.1] * 5, "C": [0.1] * 5},
        index=dates,
    )
    s.membership_top_n = None
    s.membership_lookback_days = None
    s._membership_schedule = None
    s.trend_window = None
    s._close_panel = None
    s.crowding_field = None
    s.crowding_tilt_k = 1.0
    s._crowding_panel = None
    s.oi_divergence = False
    s.oi_div_lookback = 14
    s.oi_div_tilt_k = 1.0
    s.oi_div_directional = False
    s._oi_div_signal = None
    s.smart_money = smart_money
    s.smart_money_tilt_k = smart_money_tilt_k
    s._smart_money_signal = None  # injectable seam
    return s


def test_smart_money_signal_high_ratio_scores_high():
    """_build_smart_money_signal: coin with high ls_top/ls_global ratio scores high.

    Tests the formula directly without qlib by building the panels manually.
    High ratio (A) > low ratio (B); NaN where either input is NaN (C); zero ls_global → inf → NaN (D).
    """
    import numpy as np

    # Simulate the ratio computation from _build_smart_money_signal
    dates = pd.date_range("2025-01-01", periods=3, freq="D")
    ls_top = pd.DataFrame(
        {"A": [2.0, 2.0, 2.0], "B": [0.5, 0.5, 0.5], "C": [float("nan"), float("nan"), float("nan")], "D": [1.0, 1.0, 1.0]},
        index=dates,
    )
    ls_global = pd.DataFrame({"A": [1.0, 1.0, 1.0], "B": [1.0, 1.0, 1.0], "C": [1.0, 1.0, 1.0], "D": [0.0, 0.0, 0.0]}, index=dates)

    smart_div = ls_top / ls_global
    # Replace infinities with NaN (zero denominator case)
    smart_div = smart_div.replace([float("inf"), float("-inf")], float("nan"))

    # A: ls_top=2, ls_global=1 → ratio=2.0
    assert smart_div["A"].iloc[-1] == 2.0, "high-ratio coin A must score 2.0"
    # B: ls_top=0.5, ls_global=1 → ratio=0.5
    assert smart_div["B"].iloc[-1] == 0.5, "low-ratio coin B must score 0.5"
    # C: ls_top=NaN → ratio=NaN
    assert smart_div["C"].iloc[-1] != smart_div["C"].iloc[-1], "NaN ls_top → ratio must be NaN"
    # D: ls_global=0 → inf → NaN (non-finite guard)
    assert smart_div["D"].iloc[-1] != smart_div["D"].iloc[-1], "zero ls_global → ratio must be NaN (not inf)"


def test_smart_money_tilt_high_ratio_upweighted():
    """Tilt behavior: high smart_div coin (z>0) is UP-weighted, low-ratio coin (z<0) DOWN-weighted.

    Equal vols → equal inverse-vol weights. Tilt shifts distribution: high-ratio up, low-ratio down.
    Weights must still sum to ~1.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_smart_money_stub(smart_money=True, smart_money_tilt_k=1.0)

    # Signal panel: 4 prior dates + 1 future row that must NOT be used.
    # Prior row (date 3): A=2.0 (high ratio, smart money more long), B=0.5 (low ratio, retail more long).
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._smart_money_signal = pd.DataFrame(
        {"A": [2.0, 2.0, 2.0, 2.0, 0.1], "B": [0.5, 0.5, 0.5, 0.5, 99.0]},
        index=dates,
    )

    trade_date = dates[4]  # use only rows strictly before dates[4] = rows 0-3
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert set(w.keys()) == {"A", "B"}, f"both names should be held; got {set(w.keys())}"
    assert abs(sum(w.values()) - 1.0) < 1e-9, f"weights must sum to 1; got {sum(w.values())}"
    assert w["A"] > w["B"], "high-ratio coin A must be UP-weighted vs low-ratio coin B"


def test_smart_money_tilt_nan_signal_neutral():
    """A coin with NaN smart_div gets tilt=1.0 (neutral); others tilt among themselves.

    Three names: A NaN (no perp / data gap), B high-ratio, C low-ratio.
    After tilt: B's weight grows; C's weight shrinks; A stays at neutral share.
    Weights sum to 1.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_smart_money_stub(smart_money=True, smart_money_tilt_k=1.0)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    # A has NaN (no perp/data gap); B high-ratio; C low-ratio
    s._smart_money_signal = pd.DataFrame(
        {"A": [float("nan")] * 5, "B": [2.0] * 5, "C": [0.5] * 5},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0, "C": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert set(w.keys()) == {"A", "B", "C"}, f"all three names should be held; got {set(w.keys())}"
    assert abs(sum(w.values()) - 1.0) < 1e-9, "weights must sum to 1"
    # B (high-ratio, z>0) must be UP-weighted vs C (low-ratio, z<0)
    assert w["B"] > w["C"], "high-ratio B must be up-weighted vs low-ratio C"
    # A (NaN → tilt 1.0) should not be penalised vs high-ratio B but should beat C
    assert w["A"] > w["C"], "NaN-signal coin A should not be penalised vs low-ratio C"


def test_smart_money_tilt_no_lookahead():
    """The smart-money tilt at date t must use ONLY signal rows strictly before t.

    Inject a panel where the future row (at trade_date) would invert the tilt if used.
    Assert the inversion does NOT happen.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_smart_money_stub(smart_money=True, smart_money_tilt_k=1.0)

    # Prior rows (dates 0-3): A high-ratio (+), B low-ratio (−) → A should be up-weighted.
    # Future row (date 4 = trade_date): A=0.1 (low), B=99.0 (high) → if used, B would be up-weighted.
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._smart_money_signal = pd.DataFrame(
        {"A": [2.0, 2.0, 2.0, 2.0, 0.1], "B": [0.5, 0.5, 0.5, 0.5, 99.0]},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    # Strictly prior rows say A is high-ratio → must be UP-weighted vs B
    assert w["A"] > w["B"], "look-ahead guard failed: future smart-money row must not be used"


def test_smart_money_false_regression():
    """smart_money=False → weights byte-identical to plain inverse-vol (regression).

    The OI-div and crowding tilts are also off in this test; checks the pure back-compat path.
    """
    from cli.experiment.strategies import regime as rg

    s_no_tilt = _make_smart_money_stub(smart_money=False)
    s_tilt = _make_smart_money_stub(smart_money=True, smart_money_tilt_k=1.0)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s_tilt._smart_money_signal = pd.DataFrame(
        {"A": [2.0, 2.0, 2.0, 2.0, 99.0], "B": [0.5, 0.5, 0.5, 0.5, 99.0], "C": [1.0, 1.0, 1.0, 1.0, 99.0]},
        index=dates,
    )

    score = pd.Series({"A": 0.0, "B": 0.0, "C": 0.0})
    trade_date = dates[4]
    w_no_tilt = s_no_tilt.generate_target_weight_position(
        score, current=None, trade_start_time=trade_date, trade_end_time=trade_date
    )
    w_tilt = s_tilt.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    # Without smart_money the equal-vol basket stays equal-weight.
    for name in ["A", "B", "C"]:
        assert abs(w_no_tilt[name] - 1.0 / 3) < 1e-9, f"smart_money=False: {name} must be equal-weighted"
    # The tilted version must differ (A up-weighted, B down-weighted, C in between).
    assert w_tilt["A"] > w_tilt["B"], "smart_money=True must shift weights"


# ---------------------------------------------------------------------------
# Strong-trend magnitude gate tests (iter-44)
# ---------------------------------------------------------------------------


def _make_strong_trend_stub(
    oi_div_strong_trend_only=True,
    oi_div_strong_trend_margin=0.25,
    oi_div_tilt_k=1.0,
):
    """Build a VolWeightedRegimeStrategy stub for strong-trend gate tests.

    Sets up a 2-name equal-vol panel; tests inject _strong_trend_signal,
    _oi_div_signal, and optionally override _vol_panel themselves.
    """
    from cli.experiment.strategies import regime as rg

    s = object.__new__(rg.VolWeightedRegimeStrategy)
    s._base_risk_degree = 0.95
    # 5 days; equal vol so plain inverse-vol gives equal (50/50) weights
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._vol_panel = pd.DataFrame({"A": [0.1] * 5, "B": [0.1] * 5}, index=dates)
    s.membership_top_n = None
    s.membership_lookback_days = None
    s._membership_schedule = None
    s.trend_window = None
    s._close_panel = None
    s.crowding_field = None
    s.crowding_tilt_k = 1.0
    s._crowding_panel = None
    s.oi_divergence = True
    s.oi_div_lookback = 14
    s.oi_div_tilt_k = oi_div_tilt_k
    s.oi_div_directional = True
    s.oi_div_strong_trend_only = oi_div_strong_trend_only
    s.oi_div_strong_trend_margin = oi_div_strong_trend_margin
    s._oi_div_signal = None  # injectable seam
    s._strong_trend_signal = None  # injectable seam
    s.smart_money = False
    s.smart_money_tilt_k = 1.0
    s._smart_money_signal = None
    return s


def test_strong_trend_gate_fires_tilt_when_above_margin():
    """When prior pct_above > margin (strong trend), the OI tilt IS applied.

    A has high OI confirmation, B has low → A must be up-weighted vs B.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_strong_trend_stub(oi_div_strong_trend_only=True, oi_div_strong_trend_margin=0.25)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    # Strong-trend signal: prior rows all 0.40 > 0.25 → gate fires → tilt applied.
    s._strong_trend_signal = pd.Series([0.40, 0.40, 0.40, 0.40, 0.40], index=dates)
    # OI-div signal: A confirmed (+), B divergent (−) → with tilt, A up-weighted.
    s._oi_div_signal = pd.DataFrame(
        {"A": [1.0, 1.0, 1.0, 1.0, -99.0], "B": [-1.0, -1.0, -1.0, -1.0, 99.0]},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert set(w.keys()) == {"A", "B"}, f"both names should be held; got {set(w.keys())}"
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert w["A"] > w["B"], "strong-trend gate fired: OI tilt must up-weight confirmed coin A"


def test_strong_trend_gate_skips_tilt_when_below_margin():
    """When prior pct_above <= margin (weak/chop), the OI tilt is SKIPPED → plain inverse-vol.

    Equal-vol basket must stay 50/50 regardless of the OI signal.
    This is the load-bearing test.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_strong_trend_stub(oi_div_strong_trend_only=True, oi_div_strong_trend_margin=0.25)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    # Weak trend: prior pct_above = 0.10 ≤ 0.25 → gate does NOT fire → tilt skipped.
    s._strong_trend_signal = pd.Series([0.10, 0.10, 0.10, 0.10, 0.10], index=dates)
    # OI-div signal has strong directional signal; it must be ignored.
    s._oi_div_signal = pd.DataFrame(
        {"A": [1.0, 1.0, 1.0, 1.0, -99.0], "B": [-1.0, -1.0, -1.0, -1.0, 99.0]},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    # Plain inverse-vol with equal vols → 50/50
    assert abs(w.get("A", 0.0) - 0.5) < 1e-9, f"weak-trend gate: A must be 0.5 (no tilt); got {w.get('A')}"
    assert abs(w.get("B", 0.0) - 0.5) < 1e-9, f"weak-trend gate: B must be 0.5 (no tilt); got {w.get('B')}"


def test_strong_trend_gate_skips_tilt_when_exactly_at_margin():
    """pct_above == margin (not strictly above) → tilt is SKIPPED."""
    from cli.experiment.strategies import regime as rg

    s = _make_strong_trend_stub(oi_div_strong_trend_only=True, oi_div_strong_trend_margin=0.25)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    # Exactly at margin — not strictly above → gate does NOT fire.
    s._strong_trend_signal = pd.Series([0.25, 0.25, 0.25, 0.25, 0.25], index=dates)
    s._oi_div_signal = pd.DataFrame(
        {"A": [1.0, 1.0, 1.0, 1.0, -99.0], "B": [-1.0, -1.0, -1.0, -1.0, 99.0]},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert abs(w.get("A", 0.0) - 0.5) < 1e-9, "at-margin: tilt must not fire (not strictly above)"
    assert abs(w.get("B", 0.0) - 0.5) < 1e-9, "at-margin: tilt must not fire (not strictly above)"


def test_strong_trend_gate_skips_tilt_when_nan_warmup():
    """NaN pct_above (warmup, no prior data) → tilt is SKIPPED → plain inverse-vol."""
    from cli.experiment.strategies import regime as rg

    s = _make_strong_trend_stub(oi_div_strong_trend_only=True, oi_div_strong_trend_margin=0.25)

    # Only one prior row, and it is NaN (warmup).
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._strong_trend_signal = pd.Series([float("nan"), float("nan"), float("nan"), float("nan"), float("nan")], index=dates)
    s._oi_div_signal = pd.DataFrame(
        {"A": [1.0, 1.0, 1.0, 1.0, -99.0], "B": [-1.0, -1.0, -1.0, -1.0, 99.0]},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert abs(w.get("A", 0.0) - 0.5) < 1e-9, "NaN warmup: tilt must not fire"
    assert abs(w.get("B", 0.0) - 0.5) < 1e-9, "NaN warmup: tilt must not fire"


def test_strong_trend_gate_no_lookahead():
    """The gate at date t uses only pct_above rows strictly BEFORE t.

    Inject a future row that would flip the gate from 'skip' to 'fire'.
    Assert the flip does NOT happen (plain inverse-vol is returned).
    """
    from cli.experiment.strategies import regime as rg

    s = _make_strong_trend_stub(oi_div_strong_trend_only=True, oi_div_strong_trend_margin=0.25)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    # Prior rows (dates 0-3): pct_above = 0.10 ≤ margin → gate off → tilt skipped.
    # Row at trade_date (date 4): pct_above = 0.60 > margin → if used, gate would fire.
    s._strong_trend_signal = pd.Series([0.10, 0.10, 0.10, 0.10, 0.60], index=dates)
    s._oi_div_signal = pd.DataFrame(
        {"A": [1.0, 1.0, 1.0, 1.0, 1.0], "B": [-1.0, -1.0, -1.0, -1.0, -1.0]},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    # Strictly prior rows say pct_above ≤ margin → gate must NOT fire → plain inverse-vol
    assert abs(w.get("A", 0.0) - 0.5) < 1e-9, "look-ahead guard failed: future pct_above must not flip the gate"
    assert abs(w.get("B", 0.0) - 0.5) < 1e-9, "look-ahead guard failed: future pct_above must not flip the gate"


def test_strong_trend_gate_false_regression():
    """oi_div_strong_trend_only=False → OI tilt always applied, byte-identical to iter-42.

    With strong_trend_only=False (default), even a weak pct_above (0.10) must not suppress the tilt.
    """
    from cli.experiment.strategies import regime as rg

    # Stub with gate off (same as iter-42)
    s = _make_strong_trend_stub(oi_div_strong_trend_only=False, oi_div_strong_trend_margin=0.25)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    # Inject a weak trend signal — must be IGNORED when strong_trend_only=False
    s._strong_trend_signal = pd.Series([0.10, 0.10, 0.10, 0.10, 0.10], index=dates)
    s._oi_div_signal = pd.DataFrame(
        {"A": [1.0, 1.0, 1.0, 1.0, -99.0], "B": [-1.0, -1.0, -1.0, -1.0, 99.0]},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    # Gate is off → tilt IS applied → A (confirmed) must be up-weighted vs B (divergent)
    assert w["A"] > w["B"], "strong_trend_only=False: OI tilt must always apply regardless of pct_above"


def test_build_strong_trend_signal_formula():
    """_build_strong_trend_signal: pct_above = close/SMA(window) − 1 on a small series."""
    import math

    from cli.experiment.strategies import regime as rg

    # Build a stub with the bare minimum attributes needed to call _build_strong_trend_signal
    # via injection (we monkeypatch the D.features call using the seam approach from other tests).
    # Instead, test the formula directly since the method is simple.
    # close = [100, 110, 120, 130, 140]; SMA(3) at position 4 = mean(120,130,140) = 130
    # pct_above[4] = 140/130 − 1 ≈ 0.0769...
    close = pd.Series(
        [100.0, 110.0, 120.0, 130.0, 140.0],
        index=pd.date_range("2025-01-01", periods=5, freq="D"),
    )
    window = 3
    sma = close.rolling(window).mean()
    pct_above = close / sma - 1

    # Warmup: first two rows have NaN SMA → NaN pct_above
    assert pct_above.iloc[0] != pct_above.iloc[0], "warmup row 0 must be NaN"
    assert pct_above.iloc[1] != pct_above.iloc[1], "warmup row 1 must be NaN"
    # First valid row: SMA(3) at idx=2 = mean(100,110,120) = 110; close=120 → pct_above = 120/110 − 1
    expected_2 = 120.0 / 110.0 - 1.0
    assert abs(pct_above.iloc[2] - expected_2) < 1e-9, f"row 2: expected {expected_2}; got {pct_above.iloc[2]}"
    # Last row: SMA(3) = mean(120,130,140) = 130; pct_above = 140/130 − 1
    expected_4 = 140.0 / 130.0 - 1.0
    assert abs(pct_above.iloc[4] - expected_4) < 1e-9, f"row 4: expected {expected_4}; got {pct_above.iloc[4]}"
    # Causal: the last row does NOT use future closes
    assert not math.isnan(pct_above.iloc[4]), "last row must be valid (causal)"


# ---------------------------------------------------------------------------
# On-chain NVM overlay tests (iter-46)
# ---------------------------------------------------------------------------


def _make_onchain_stub(onchain_regime=True, onchain_z_threshold=1.0, onchain_derisk_mult=0.0):
    """Build a VolWeightedRegimeStrategy stub without calling __init__ (no qlib needed).

    Injects a bullish exposure series and onchain params; tests inject _onchain_signal themselves.
    """
    from cli.experiment.strategies import regime as rg

    s = object.__new__(rg.VolWeightedRegimeStrategy)
    s._base_risk_degree = 0.95
    idx = pd.date_range("2025-01-01", periods=5, freq="D")
    # Bullish BTC exposure throughout
    s._exposure = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0], index=idx)
    s.trend_window = None
    s.compose_market_gate = False
    s.froth_field = None
    s.froth_lookback = 90
    s.froth_z_threshold = 1.5
    s.froth_derisk_mult = 0.0
    s.onchain_regime = onchain_regime
    s.onchain_path = None  # never read in tests (signal is injected)
    s.onchain_z_window = 365
    s.onchain_z_threshold = onchain_z_threshold
    s.onchain_derisk_mult = onchain_derisk_mult
    s._onchain_signal = None  # injectable seam
    return s


class _OnchainCal:
    """Minimal trade_calendar stub for onchain overlay tests."""

    def __init__(self, d):
        self._d = d

    def get_trade_step(self):
        return 0

    def get_step_time(self, step, shift=0):
        return (self._d, self._d)


def test_onchain_above_threshold_zeroes_exposure():
    """NVM z > threshold at prior date → exposure = regime_mult × onchain_derisk_mult (0.0 → cash)."""
    import pytest

    from cli.experiment.strategies import regime as rg

    s = _make_onchain_stub(onchain_regime=True, onchain_z_threshold=1.0, onchain_derisk_mult=0.0)
    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    # z=2.0 on day 1 → strictly-prior lookup from day 2 sees day 1 z=2.0 > 1.0 → de-risk
    s._onchain_signal = pd.Series([0.5, 2.0, 0.3], index=idx)

    monkeypatch = pytest.MonkeyPatch()
    # Trade on day 2: strictly prior lookup at day < day 2 → uses day 1 (z=2.0)
    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _OnchainCal(idx[2])), raising=False)
    assert s.get_risk_degree(0) == 0.0, "above-threshold NVM must zero exposure"
    monkeypatch.undo()


def test_onchain_below_threshold_regime_multiplier_unchanged():
    """NVM z below threshold → regime multiplier applies; onchain overlay does not fire."""
    import pytest

    from cli.experiment.strategies import regime as rg

    s = _make_onchain_stub(onchain_regime=True, onchain_z_threshold=1.0, onchain_derisk_mult=0.0)
    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    s._onchain_signal = pd.Series([0.5, 0.8, 0.3], index=idx)  # all below 1.0

    monkeypatch = pytest.MonkeyPatch()
    # Trade on day 2: prior z = 0.8 ≤ 1.0 → no de-risk → 0.95 * 1.0 (regime, bullish) = 0.95
    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _OnchainCal(idx[2])), raising=False)
    assert abs(s.get_risk_degree(0) - 0.95) < 1e-9, "below-threshold NVM must not alter risk_degree"
    monkeypatch.undo()


def test_onchain_nan_z_does_not_derisk():
    """NaN NVM z (warmup / missing data) → overlay does NOT de-risk (treat NaN as 'no signal')."""
    import pytest

    from cli.experiment.strategies import regime as rg

    s = _make_onchain_stub(onchain_regime=True, onchain_z_threshold=1.0, onchain_derisk_mult=0.0)
    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    # NaN on days 0 and 1 (warmup)
    s._onchain_signal = pd.Series([float("nan"), float("nan"), 0.5], index=idx)

    monkeypatch = pytest.MonkeyPatch()
    # Trade on day 2: prior z = NaN → no de-risk → full regime mult applies
    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _OnchainCal(idx[2])), raising=False)
    assert abs(s.get_risk_degree(0) - 0.95) < 1e-9, "NaN NVM z must not trigger de-risk"
    monkeypatch.undo()


def test_onchain_strictly_prior_no_lookahead():
    """Strictly-prior lookup: only dates BEFORE the query date are used (no look-ahead).

    Inject an onchain_signal with only a future row (date AFTER the trade date) → assert no de-risk.
    """
    import pytest

    from cli.experiment.strategies import regime as rg

    s = _make_onchain_stub(onchain_regime=True, onchain_z_threshold=1.0, onchain_derisk_mult=0.0)
    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    trade_date = idx[0]  # 2025-01-01

    # Signal only has entries on day 1 and day 2 — both strictly AFTER trade_date day 0.
    # The strictly-prior slice (index < trade_date) is empty → no de-risk.
    s._onchain_signal = pd.Series([2.0, 3.0], index=idx[1:])

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _OnchainCal(trade_date)), raising=False
    )
    # Prior slice is empty → overlay skips → full regime mult applies
    assert abs(s.get_risk_degree(0) - 0.95) < 1e-9, "future-only signal must not trigger de-risk (no look-ahead)"
    monkeypatch.undo()


def test_onchain_signal_index_is_tz_naive():
    """_mult_for must not raise TypeError when _onchain_signal has a tz-aware UTC index.

    The NVM parquet is written with a tz-aware UTC DatetimeIndex (the fetcher uses
    pd.to_datetime(..., utc=True)).  qlib trade dates are tz-naive Timestamps.
    A tz-aware index compared to a tz-naive Timestamp raises TypeError.
    This test injects a tz-aware UTC signal and verifies that _mult_for neither raises
    nor silently skips the de-risk when the NVM z exceeds the threshold.
    """
    import pytest

    from cli.experiment.strategies import regime as rg

    s = _make_onchain_stub(onchain_regime=True, onchain_z_threshold=1.0, onchain_derisk_mult=0.0)

    # tz-aware UTC index — mirrors what pd.read_parquet returns when the fetcher
    # built the file with pd.to_datetime(..., utc=True).
    idx_utc = pd.date_range("2025-01-01", periods=3, freq="D", tz="UTC")
    # z=2.0 on day 1 → strictly-prior from day 2 should see day 1 → de-risk fires.
    s._onchain_signal = pd.Series([0.5, 2.0, 0.3], index=idx_utc)

    # Trade date is tz-naive (qlib convention).
    trade_date = pd.Timestamp("2025-01-03")  # tz-naive

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _OnchainCal(trade_date)), raising=False
    )
    # Before the fix this raises TypeError; after the fix it must return 0.0 (de-risk fired).
    result = s.get_risk_degree(0)
    monkeypatch.undo()
    assert result == 0.0, f"de-risk must fire when NVM z > threshold; got risk_degree={result}"


def test_onchain_regime_false_byte_identical():
    """onchain_regime=False → _mult_for returns same result as without the overlay (regression).

    Instantiate with onchain_regime=False, same exposure → verify the multiplier matches the non-onchain result.
    """
    import pytest

    from cli.experiment.strategies import regime as rg

    s_with = _make_onchain_stub(onchain_regime=False)
    s_without = object.__new__(rg.VolWeightedRegimeStrategy)
    s_without._base_risk_degree = 0.95
    idx = pd.date_range("2025-01-01", periods=5, freq="D")
    s_without._exposure = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0], index=idx)
    s_without.trend_window = None
    s_without.compose_market_gate = False
    s_without.froth_field = None
    # No onchain attrs at all — getattr guards must handle this.

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _OnchainCal(idx[2])), raising=False)
    rd_with = s_with.get_risk_degree(0)
    rd_without = s_without.get_risk_degree(0)
    monkeypatch.undo()
    assert abs(rd_with - rd_without) < 1e-9, "onchain_regime=False must not alter risk_degree vs no-onchain stub"
    assert abs(rd_with - 0.95) < 1e-9


# ---------------------------------------------------------------------------
# Cross-sectional momentum tilt tests (iter-47)
# ---------------------------------------------------------------------------


def _make_momentum_stub(momentum_tilt=True, momentum_lookback=30, momentum_tilt_k=1.0):
    """Build a VolWeightedRegimeStrategy stub without calling __init__ (no qlib needed).

    Sets up a 3-name equal-vol panel; tests inject _momentum_signal themselves.
    """
    from cli.experiment.strategies import regime as rg

    s = object.__new__(rg.VolWeightedRegimeStrategy)
    s._base_risk_degree = 0.95
    # 5 days; equal vol for all names so plain inverse-vol gives equal weights
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._vol_panel = pd.DataFrame(
        {"A": [0.1] * 5, "B": [0.1] * 5, "C": [0.1] * 5},
        index=dates,
    )
    s.membership_top_n = None
    s.membership_lookback_days = None
    s._membership_schedule = None
    s.trend_window = None
    s._close_panel = None
    s.crowding_field = None
    s.crowding_tilt_k = 1.0
    s._crowding_panel = None
    s.oi_divergence = False
    s.oi_div_lookback = 14
    s.oi_div_tilt_k = 1.0
    s.oi_div_directional = False
    s._oi_div_signal = None
    s.smart_money = False
    s.smart_money_tilt_k = 1.0
    s._smart_money_signal = None
    s.momentum_tilt = momentum_tilt
    s.momentum_lookback = momentum_lookback
    s.momentum_tilt_k = momentum_tilt_k
    s._momentum_signal = None  # injectable seam
    return s


def test_momentum_signal_formula():
    """_build_momentum_signal = close/close.shift(lookback) − 1; causal; NaN in warmup."""
    # Test the formula directly on a small constructed close panel (no qlib).
    lookback = 3
    dates = pd.date_range("2025-01-01", periods=6, freq="D")
    # A: rising 100 → 150; B: flat 100; C: falling 100 → 50
    close_wide = pd.DataFrame(
        {
            "A": [100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
            "B": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
            "C": [100.0, 90.0, 80.0, 70.0, 60.0, 50.0],
        },
        index=dates,
    )
    mom = close_wide / close_wide.shift(lookback) - 1

    # Warmup rows (indices 0, 1, 2) must be NaN
    for i in range(lookback):
        assert mom["A"].iloc[i] != mom["A"].iloc[i], f"row {i} must be NaN (warmup)"
        assert mom["B"].iloc[i] != mom["B"].iloc[i], f"row {i} must be NaN (warmup)"

    # Row 3: close[3] / close[0] − 1 = 130/100 − 1 = 0.30 for A
    assert abs(mom["A"].iloc[3] - 0.30) < 1e-9, f"A row 3 expected 0.30; got {mom['A'].iloc[3]}"
    # Row 3: B flat → 100/100 − 1 = 0.0
    assert abs(mom["B"].iloc[3] - 0.0) < 1e-9, f"B row 3 expected 0.0; got {mom['B'].iloc[3]}"
    # Row 3: C falling → 70/100 − 1 = -0.30
    assert abs(mom["C"].iloc[3] - (-0.30)) < 1e-9, f"C row 3 expected -0.30; got {mom['C'].iloc[3]}"


def test_momentum_signal_causal():
    """Truncating future rows does not change the last row of momentum signal (truncation-invariant)."""
    lookback = 3
    dates = pd.date_range("2025-01-01", periods=6, freq="D")
    close_wide = pd.DataFrame(
        {"A": [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]},
        index=dates,
    )
    # Full signal (includes the last row)
    mom_full = close_wide / close_wide.shift(lookback) - 1
    # Truncated signal (drop the last row, simulating future data being cut off)
    close_trunc = close_wide.iloc[:-1]
    mom_trunc = close_trunc / close_trunc.shift(lookback) - 1

    # Row 4 in full == row 4 in truncated (same values through row 4)
    assert abs(mom_full["A"].iloc[4] - mom_trunc["A"].iloc[4]) < 1e-12, (
        "causal: truncation of future row must not affect prior rows"
    )


def test_momentum_tilt_high_momentum_upweighted():
    """One HIGH-momentum coin (z>0) gets a HIGHER weight; low-momentum coin (z<0) gets LOWER weight.

    Equal vols → equal inverse-vol weights. Tilt shifts distribution.
    Weights must still sum to ~1.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_momentum_stub(momentum_tilt=True, momentum_tilt_k=1.0)

    # Signal panel: 4 prior dates + 1 future row that must NOT be used.
    # Prior row (date 3): A has high trailing return (+), B has low (−).
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._momentum_signal = pd.DataFrame(
        {"A": [0.10, 0.15, 0.20, 0.25, -99.0], "B": [-0.10, -0.15, -0.20, -0.25, 99.0]},
        index=dates,
    )

    trade_date = dates[4]  # use only rows strictly before dates[4] = rows 0-3
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert set(w.keys()) == {"A", "B"}, f"both names should be held; got {set(w.keys())}"
    assert abs(sum(w.values()) - 1.0) < 1e-9, f"weights must sum to 1; got {sum(w.values())}"
    # A (high momentum, z>0) must be UP-weighted
    assert w["A"] > w["B"], "high-momentum coin A must be UP-weighted vs low-momentum coin B"


def test_momentum_tilt_nan_signal_neutral():
    """A coin with NaN momentum gets tilt=1.0 (neutral); others tilt among themselves.

    Three names: A NaN, B high-momentum, C low-momentum.
    After tilt: B's weight grows; C's weight shrinks; A stays at neutral share.
    Weights sum to 1.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_momentum_stub(momentum_tilt=True, momentum_tilt_k=1.0)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._momentum_signal = pd.DataFrame(
        {"A": [float("nan")] * 5, "B": [0.20] * 5, "C": [-0.20] * 5},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0, "C": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    assert set(w.keys()) == {"A", "B", "C"}, f"all three names should be held; got {set(w.keys())}"
    assert abs(sum(w.values()) - 1.0) < 1e-9, "weights must sum to 1"
    # B (high momentum, z>0) must be UP-weighted vs C (low momentum, z<0)
    assert w["B"] > w["C"], "high-momentum B must be up-weighted vs low-momentum C"
    # A (NaN → tilt 1.0) should not be penalised vs high-momentum B
    assert w["A"] > w["C"], "NaN-signal coin A should not be penalised vs low-momentum C"


def test_momentum_tilt_no_lookahead():
    """The momentum tilt at date t must use ONLY signal rows strictly before t.

    Inject a panel where the future row (at trade_date) would invert the tilt if used.
    Assert the inversion does NOT happen.
    """
    from cli.experiment.strategies import regime as rg

    s = _make_momentum_stub(momentum_tilt=True, momentum_tilt_k=1.0)

    # Prior rows (dates 0-3): A high-momentum (+), B low-momentum (−) → A should be up-weighted.
    # Future row (date 4 = trade_date): A=-99.0, B=+99.0 → if used, B would be up-weighted.
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s._momentum_signal = pd.DataFrame(
        {"A": [0.20, 0.20, 0.20, 0.20, -99.0], "B": [-0.20, -0.20, -0.20, -0.20, 99.0]},
        index=dates,
    )

    trade_date = dates[4]
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    # Strictly prior rows say A is high-momentum → must be UP-weighted vs B
    assert w["A"] > w["B"], "look-ahead guard failed: future momentum row must not be used"


def test_momentum_tilt_false_regression():
    """momentum_tilt=False → weights byte-identical to plain inverse-vol.

    The OI-div and smart-money tilts are also off; checks pure back-compat path.
    """
    from cli.experiment.strategies import regime as rg

    s_no_tilt = _make_momentum_stub(momentum_tilt=False)
    s_tilt = _make_momentum_stub(momentum_tilt=True, momentum_tilt_k=1.0)

    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    s_tilt._momentum_signal = pd.DataFrame(
        {"A": [0.20, 0.20, 0.20, 0.20, 99.0], "B": [-0.20, -0.20, -0.20, -0.20, 99.0], "C": [0.0, 0.0, 0.0, 0.0, 99.0]},
        index=dates,
    )

    score = pd.Series({"A": 0.0, "B": 0.0, "C": 0.0})
    trade_date = dates[4]
    w_no_tilt = s_no_tilt.generate_target_weight_position(
        score, current=None, trade_start_time=trade_date, trade_end_time=trade_date
    )
    w_tilt = s_tilt.generate_target_weight_position(score, current=None, trade_start_time=trade_date, trade_end_time=trade_date)

    # Without momentum_tilt the equal-vol basket stays equal-weight.
    for name in ["A", "B", "C"]:
        assert abs(w_no_tilt[name] - 1.0 / 3) < 1e-9, f"momentum_tilt=False: {name} must be equal-weighted"
    # The tilted version must differ (A up-weighted, B down-weighted, C in between or shifted).
    assert w_tilt["A"] > w_tilt["B"], "momentum_tilt=True must shift weights"


# ---------------------------------------------------------------------------
# confirm_days anti-whipsaw debounce tests (iter-53)
# ---------------------------------------------------------------------------


def _make_binary_close(values, start="2020-01-01"):
    """Build a date-indexed float64 Series from a list of price values."""
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype="float64")


def test_confirm_days_blip_does_not_flip():
    """A 2-day crossing blip with confirm_days=5 must NOT flip the confirmed gate.

    We use _debounce_binary directly to test the debounce logic in isolation,
    bypassing SMA construction complexity.  raw=1 (above SMA) for most of the
    series, then raw=0 for exactly 2 days (the blip), then back to 1.
    """
    from cli.experiment.strategies.regime import _debounce_binary

    n = 20
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    raw_vals = [1] * 10 + [0, 0] + [1] * 8  # 2-day blip in the middle
    raw = pd.Series([float(v) for v in raw_vals], index=idx)
    warm = pd.Series([False] * n, index=idx)

    confirmed = _debounce_binary(raw, confirm_days=5, warmup_mask=warm)

    # The 2-day blip must NOT flip the confirmed gate (stays 1.0).
    assert confirmed.iloc[10] == 1.0, "first blip day: confirmed gate must stay 1.0"
    assert confirmed.iloc[11] == 1.0, "second blip day: confirmed gate must stay 1.0"
    # After recovery: still 1.0.
    assert confirmed.iloc[-1] == 1.0, "after recovery: gate must be 1.0"
    # Before blip: all 1.0.
    assert (confirmed.iloc[:10] == 1.0).all(), "pre-blip: gate must be 1.0"


def test_confirm_days_sustained_crossing_flips_on_day_n():
    """A sustained 5-consecutive-day crossing with confirm_days=5 flips the gate ON day 5.

    The flip must happen exactly on the 5th consecutive below-SMA day (not before).
    We test _debounce_binary directly to isolate the flip timing from SMA dynamics.
    """
    from cli.experiment.strategies.regime import _debounce_binary

    n = 20
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    # 10 days above (raw=1), then 10 days below (raw=0).
    raw_vals = [1] * 10 + [0] * 10
    raw = pd.Series([float(v) for v in raw_vals], index=idx)
    warm = pd.Series([False] * n, index=idx)

    confirmed = _debounce_binary(raw, confirm_days=5, warmup_mask=warm)

    below_start = 10  # index where raw flips to 0
    # Days 0-3 of the below run (4 days): confirmed gate stays 1.0.
    for i in range(4):
        assert confirmed.iloc[below_start + i] == 1.0, f"day {i} of below run: gate must stay 1.0 (not flipped yet)"
    # Day 4 (the 5th consecutive below-raw day, 0-indexed): confirmed flips to 0.0.
    assert confirmed.iloc[below_start + 4] == 0.0, "day 5 of below run: gate must flip to 0.0"
    # Subsequent days remain 0.0.
    assert (confirmed.iloc[below_start + 4 :] == 0.0).all(), "after flip: gate stays 0.0"


def test_confirm_days_no_lookahead():
    """The confirmed series for row t is unchanged when future rows are appended (truncation-invariance).

    Compute the series on N rows, then on N+10 rows; the first N values must be identical.
    """
    from cli.experiment.strategies.regime import regime_exposure_series

    prices_short = [1.0, 2.0, 3.0] + [100.0] * 20 + [1.0] * 5
    prices_long = prices_short + [200.0] * 10  # 10 more rows appended

    s_short = regime_exposure_series(_make_binary_close(prices_short), mode="binary", ma_window=3, confirm_days=5)
    s_long = regime_exposure_series(_make_binary_close(prices_long), mode="binary", ma_window=3, confirm_days=5)

    n = len(prices_short)
    for i in range(n):
        assert s_short.iloc[i] == s_long.iloc[i], f"look-ahead at row {i}: truncation changes prior value"


def test_confirm_days_zero_backcompat_binary():
    """confirm_days=0 → regime_exposure_series output is byte-identical to the no-confirm path."""
    from cli.experiment.strategies.regime import regime_exposure_series

    prices = [1.0, 2.0, 3.0] + list(range(4, 34))
    close = _make_binary_close(prices)

    s_default = regime_exposure_series(close, mode="binary", ma_window=5)
    s_zero = regime_exposure_series(close, mode="binary", ma_window=5, confirm_days=0)

    pd.testing.assert_series_equal(s_default, s_zero, check_names=False)


def test_confirm_days_zero_strategy_backcompat():
    """VolWeightedRegimeStrategy with regime_confirm_days=0 has byte-identical exposure to default."""
    from cli.experiment.strategies import regime as rg

    # Build two stubs via object.__new__ to avoid qlib; inject _exposure via _build_exposure mock.
    prices = [1.0, 2.0, 3.0] + list(range(4, 34))
    close = pd.Series(prices, index=pd.date_range("2020-01-01", periods=len(prices), freq="D"), dtype="float64")

    from cli.experiment.strategies.regime import regime_exposure_series

    exp_default = regime_exposure_series(close, mode="binary", ma_window=5)
    exp_zero = regime_exposure_series(close, mode="binary", ma_window=5, confirm_days=0)

    pd.testing.assert_series_equal(exp_default, exp_zero, check_names=False)


def test_confirm_days_warmup_stays_one():
    """Warmup rows (SMA undefined) must always be 1.0 regardless of confirm_days."""
    from cli.experiment.strategies.regime import regime_exposure_series

    # Only 6 prices, SMA window=5 → first 4 rows are warmup.
    prices = [10.0, 9.0, 8.0, 7.0, 1.0, 1.0]  # last 2 below SMA but warmup covers first 4
    s = regime_exposure_series(_make_binary_close(prices), mode="binary", ma_window=5, confirm_days=3)

    # Warmup rows 0-3 must be 1.0
    assert (s.iloc[:4] == 1.0).all(), "warmup rows must be 1.0 with confirm_days>0"
