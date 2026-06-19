import numpy as np
import pandas as pd

from cli.experiment.features.cross_asset import cross_asset_features


def _panel():
    idx = pd.date_range("2020-01-01", periods=120, freq="D")
    rng = np.random.default_rng(0)
    btc = 100 + np.cumsum(rng.normal(0, 1, 120))
    return pd.DataFrame(
        {
            "BTCUSDT": btc,
            "ETHUSDT": btc * 1.1 + rng.normal(0, 1, 120),
            "XRPUSDT": 50 + np.cumsum(rng.normal(0, 0.5, 120)),
        },
        index=idx,
    )


def test_expected_columns():
    f = cross_asset_features(_panel(), btc="BTCUSDT")
    expected = {
        "rs_5",
        "rs_20",
        "beta_20",
        "beta_60",
        "leadlag_1",
        "leadlag_2",
        "leadlag_3",
        "coint_z",
        "csrank_mom",
        "csrank_vol",
    }
    assert expected.issubset(set(f.columns))


def test_index_names():
    f = cross_asset_features(_panel(), btc="BTCUSDT")
    assert f.index.names == ["datetime", "instrument"]


def test_btc_self_row_is_neutral():
    f = cross_asset_features(_panel(), btc="BTCUSDT")
    btc = f.xs("BTCUSDT", level="instrument")
    assert abs(btc["rs_20"].iloc[-1]) < 1e-9
    assert abs(btc["beta_20"].iloc[-1] - 1.0) < 1e-6


def test_leak_safe_trailing():
    p = _panel()
    full = cross_asset_features(p, btc="BTCUSDT")
    truncated = cross_asset_features(p.iloc[:100], btc="BTCUSDT")
    t = p.index[99]
    a = full.xs(t, level="datetime").sort_index()
    b = truncated.xs(t, level="datetime").sort_index()
    pd.testing.assert_frame_equal(a, b, check_like=True)


def test_finite_after_warmup():
    f = cross_asset_features(_panel(), btc="BTCUSDT")
    # after warmup (row index 60+) non-BTC rows should be fully finite
    # BTC's leadlag_* are NaN by design (BTC vs itself shifted is neutral/undefined)
    warm = f.xs(pd.Timestamp("2020-03-15"), level="datetime")
    non_btc = warm.drop(index="BTCUSDT")
    assert np.all(np.isfinite(non_btc.values))


def test_no_inf():
    f = cross_asset_features(_panel(), btc="BTCUSDT")
    # no inf anywhere (NaN is allowed in warmup)
    assert not np.any(np.isinf(f.values))


def test_btc_leadlag_rows_present():
    """BTC leadlag rows should exist (NaN value) not be dropped silently."""
    f = cross_asset_features(_panel(), btc="BTCUSDT")
    btc = f.xs("BTCUSDT", level="instrument")
    # BTC leadlag should be NaN (undefined), but the row must exist
    assert "leadlag_1" in btc.columns
    assert btc["leadlag_1"].isna().all() or btc["leadlag_1"].iloc[-1] != btc["leadlag_1"].iloc[-1]


def test_leak_safe_interior():
    """Stronger leak check: verify value at an interior date (not last of truncated panel)."""
    p = _panel()
    # Full panel 120 rows; truncated to 110; check at row 90 (interior for both)
    full = cross_asset_features(p, btc="BTCUSDT")
    truncated = cross_asset_features(p.iloc[:110], btc="BTCUSDT")
    t = p.index[89]
    a = full.xs(t, level="datetime").sort_index()
    b = truncated.xs(t, level="datetime").sort_index()
    pd.testing.assert_frame_equal(a, b, check_like=True)
