import numpy as np
import pandas as pd

from cli.experiment.features.funding import funding_features

_COLS = {"funding_level", "funding_z", "funding_csrank", "funding_ma", "funding_chg"}


def _panel():
    idx = pd.date_range("2020-01-01", periods=120, freq="D")
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "BTCUSDT": rng.normal(0.0001, 0.0005, 120),
            "ETHUSDT": rng.normal(0.0002, 0.0006, 120),
            "XRPUSDT": rng.normal(-0.0001, 0.0004, 120),
        },
        index=idx,
    )


def test_expected_columns():
    f = funding_features(_panel())
    assert _COLS.issubset(set(f.columns))


def test_index_names():
    f = funding_features(_panel())
    assert f.index.names == ["datetime", "instrument"]


def test_csrank_in_unit_interval():
    f = funding_features(_panel())
    r = f["funding_csrank"].dropna()
    assert (r > 0).all() and (r <= 1.0).all()


def test_leak_safe_trailing():
    p = _panel()
    full = funding_features(p)
    truncated = funding_features(p.iloc[:100])
    t = p.index[99]
    a = full.xs(t, level="datetime").sort_index()
    b = truncated.xs(t, level="datetime").sort_index()
    pd.testing.assert_frame_equal(a, b, check_like=True)


def test_finite_after_warmup():
    f = funding_features(_panel())
    warm = f.xs(pd.Timestamp("2020-03-15"), level="datetime")  # day 74 > 30-day warmup
    assert np.all(np.isfinite(warm.values))


def test_no_inf():
    f = funding_features(_panel())
    assert not np.any(np.isinf(f.values))


def test_nan_funding_column_does_not_crash_or_inf():
    p = _panel()
    p["BTCEUR"] = np.nan  # a reference pair with no funding coverage
    f = funding_features(p)
    assert not np.any(np.isinf(f.values))
    # the NaN-funding instrument's level is NaN (resolved downstream by Fillna)
    assert f.xs("BTCEUR", level="instrument")["funding_level"].isna().all()


def test_processor_appends_feature_columns(monkeypatch):
    from cli.experiment.features import funding as fmod

    panel = _panel()
    monkeypatch.setattr(fmod, "_load_funding", lambda insts, start, end: panel)

    idx = pd.MultiIndex.from_product([panel.index, ["BTCUSDT", "ETHUSDT", "XRPUSDT"]], names=["datetime", "instrument"])
    df = pd.DataFrame({("feature", "EXISTING"): 0.0}, index=idx)

    out = fmod.FundingRateProcessor()(df)
    for name in _COLS:
        assert ("feature", name) in out.columns
    assert ("feature", "EXISTING") in out.columns  # original column preserved
