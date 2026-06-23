"""Unit tests for derivatives_features and DerivativesProcessor.

Mirrors tests/test_funding_feature.py: synthetic multi-field panel, no network,
monkeypatches _load_derivatives for the Processor tests.
"""

import numpy as np
import pandas as pd
import pytest

from cli.experiment.features.derivatives import derivatives_features

_FIELDS = ("oi", "oi_value", "ls_top", "ls_global", "taker_ratio", "basis")
_PER_FIELD_SUFFIXES = ("level", "change", "csrank", "z")
# expected per-field columns
_PER_FIELD_COLS = {f"{f}_{s}" for f in _FIELDS for s in _PER_FIELD_SUFFIXES}
# derived columns
_DERIVED_COLS = {"oi_confirm", "smart_div"}
_ALL_EXPECTED = _PER_FIELD_COLS | _DERIVED_COLS


def _panels():
    """Small synthetic multi-field wide panels for testing."""
    n = 120
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    insts = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
    rng = np.random.default_rng(42)

    def _wide(base, scale):
        return pd.DataFrame(rng.normal(base, scale, (n, 3)), index=idx, columns=insts)

    return {
        "$oi": _wide(1e9, 1e8),
        "$oi_value": _wide(5e8, 5e7),
        "$ls_top": _wide(0.55, 0.05),
        "$ls_global": _wide(0.52, 0.03),
        "$taker_ratio": _wide(0.50, 0.04),
        "$basis": _wide(0.001, 0.0005),
        "$close": _wide(30000, 1000),
    }


def test_expected_columns():
    f = derivatives_features(_panels())
    assert _ALL_EXPECTED.issubset(set(f.columns))


def test_index_names():
    f = derivatives_features(_panels())
    assert f.index.names == ["datetime", "instrument"]


def test_csrank_in_unit_interval():
    f = derivatives_features(_panels())
    for field in _FIELDS:
        col = f[f"{field}_csrank"].dropna()
        assert (col > 0).all() and (col <= 1.0).all(), f"{field}_csrank out of (0,1]"


def test_level_equals_raw_panel():
    panels = _panels()
    f = derivatives_features(panels)
    # oi_level at a given datetime/instrument should equal the raw $oi value
    t = panels["$oi"].index[60]
    raw = panels["$oi"].loc[t, "BTCUSDT"]
    computed = f.xs(t, level="datetime").loc["BTCUSDT", "oi_level"]
    assert np.isclose(raw, computed)


def test_change_formula():
    panels = _panels()
    f = derivatives_features(panels, chg_window=5)
    t = panels["$oi"].index[60]
    t_prev = panels["$oi"].index[55]
    raw_now = panels["$oi"].loc[t, "BTCUSDT"]
    raw_prev = panels["$oi"].loc[t_prev, "BTCUSDT"]
    expected = raw_now / raw_prev - 1
    computed = f.xs(t, level="datetime").loc["BTCUSDT", "oi_change"]
    assert np.isclose(expected, computed)


def test_z_uses_trailing_window_only():
    panels = _panels()
    f = derivatives_features(panels, z_window=30)
    t = panels["$oi"].index[60]
    raw = panels["$oi"].iloc[:61]["BTCUSDT"]
    mean = raw.rolling(30).mean().iloc[-1]
    std = raw.rolling(30).std().iloc[-1]
    expected = (raw.iloc[-1] - mean) / std
    computed = f.xs(t, level="datetime").loc["BTCUSDT", "oi_z"]
    assert np.isclose(expected, computed)


def test_smart_div_formula():
    panels = _panels()
    f = derivatives_features(panels)
    t = panels["$ls_top"].index[60]
    top = panels["$ls_top"].loc[t, "BTCUSDT"]
    glob = panels["$ls_global"].loc[t, "BTCUSDT"]
    expected = top / glob
    computed = f.xs(t, level="datetime").loc["BTCUSDT", "smart_div"]
    assert np.isclose(expected, computed)


def test_smart_div_zero_denominator_is_nan():
    panels = _panels()
    # force a zero in ls_global at a specific point
    t = panels["$ls_global"].index[50]
    panels["$ls_global"].loc[t, "BTCUSDT"] = 0.0
    f = derivatives_features(panels)
    val = f.xs(t, level="datetime").loc["BTCUSDT", "smart_div"]
    assert not np.isfinite(val) or np.isnan(val)


def test_oi_confirm_sign():
    """oi_confirm = sign(close_chg) * oi_chg — check sign relationship."""
    panels = _panels()
    f = derivatives_features(panels, chg_window=5)
    t = panels["$close"].index[60]
    close_chg = panels["$close"].iloc[60]["BTCUSDT"] / panels["$close"].iloc[55]["BTCUSDT"] - 1
    oi_chg = panels["$oi"].iloc[60]["BTCUSDT"] / panels["$oi"].iloc[55]["BTCUSDT"] - 1
    expected = np.sign(close_chg) * oi_chg
    computed = f.xs(t, level="datetime").loc["BTCUSDT", "oi_confirm"]
    assert np.isclose(expected, computed)


def test_leak_safe_trailing():
    """A row at day 99 must be identical whether we use the full panel or truncate at day 99."""
    panels = _panels()
    truncated = {k: v.iloc[:100] for k, v in panels.items()}
    full = derivatives_features(panels)
    trunc = derivatives_features(truncated)
    t = panels["$oi"].index[99]
    a = full.xs(t, level="datetime").sort_index()
    b = trunc.xs(t, level="datetime").sort_index()
    # use check_exact=False because floats may be computed with full vs truncated rolling
    pd.testing.assert_frame_equal(a, b, check_like=True)


def test_no_inf():
    f = derivatives_features(_panels())
    assert not np.any(np.isinf(f.fillna(0).values))


def test_nan_field_propagates():
    panels = _panels()
    panels["$oi"]["BTCUSDT"] = np.nan
    f = derivatives_features(panels)
    oi_lev = f.xs("BTCUSDT", level="instrument")["oi_level"]
    assert oi_lev.isna().all()


def test_nan_ls_global_smart_div_nan():
    panels = _panels()
    panels["$ls_global"]["BTCUSDT"] = np.nan
    f = derivatives_features(panels)
    smart = f.xs("BTCUSDT", level="instrument")["smart_div"]
    assert smart.isna().all()


def test_processor_appends_feature_columns(monkeypatch):
    from cli.experiment.features import derivatives as dmod

    panels = _panels()
    monkeypatch.setattr(dmod, "_load_derivatives", lambda insts, start, end: panels)

    oi_panel = panels["$oi"]
    idx = pd.MultiIndex.from_product(
        [oi_panel.index, ["BTCUSDT", "ETHUSDT", "XRPUSDT"]],
        names=["datetime", "instrument"],
    )
    df = pd.DataFrame({("feature", "EXISTING"): 0.0}, index=idx)

    out = dmod.DerivativesProcessor()(df)
    for col in _ALL_EXPECTED:
        assert ("feature", col) in out.columns, f"Missing column: ('feature', {col!r})"
    assert ("feature", "EXISTING") in out.columns  # original column preserved


def test_processor_preserves_existing_columns(monkeypatch):
    from cli.experiment.features import derivatives as dmod

    panels = _panels()
    monkeypatch.setattr(dmod, "_load_derivatives", lambda insts, start, end: panels)

    oi_panel = panels["$oi"]
    idx = pd.MultiIndex.from_product(
        [oi_panel.index, ["BTCUSDT", "ETHUSDT", "XRPUSDT"]],
        names=["datetime", "instrument"],
    )
    df = pd.DataFrame(
        {("feature", "ALPHA"): 1.0, ("label", "LABEL0"): 0.5},
        index=idx,
    )
    out = dmod.DerivativesProcessor()(df)
    assert ("feature", "ALPHA") in out.columns
    assert ("label", "LABEL0") in out.columns
