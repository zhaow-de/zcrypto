import math
from datetime import date

import pytest

from cli.example.dataset import build_provider


def _init_qlib(provider):
    import qlib
    from qlib.constant import REG_US

    qlib.init(provider_uri=provider, region=REG_US)


def test_build_provider_roundtrip(tmp_path):
    csv = tmp_path / "toy.csv"
    csv.write_text(
        "date,symbol,open,high,low,close,volume\n"
        "2026-01-01,AAAUSD,10,11,9,10.5,100\n"
        "2026-01-02,AAAUSD,10.5,12,10,11.5,120\n"
        "2026-01-03,AAAUSD,11.5,12,11,11.0,90\n"
    )
    provider = build_provider(csv, tmp_path / "qlib_data")

    _init_qlib(provider)
    from qlib.data import D

    df = D.features(["AAAUSD"], ["$close", "$open", "$volume"], freq="day")

    assert df["$close"].tolist() == pytest.approx([10.5, 11.5, 11.0])
    assert df["$open"].tolist() == pytest.approx([10.0, 10.5, 11.5])
    assert df["$volume"].tolist() == pytest.approx([100.0, 120.0, 90.0])
    dates = [idx[1].date() for idx in df.index]
    assert dates == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]


def test_build_provider_multi_symbol_staggered(tmp_path):
    # CCCUSD spans all 3 days; BBBUSD is missing the first calendar date.
    # Distinct symbol names (not AAAUSD) avoid Qlib in-memory cache collisions
    # with the first test within the same session.
    csv = tmp_path / "multi.csv"
    csv.write_text(
        "date,symbol,open,high,low,close,volume\n"
        "2026-01-01,CCCUSD,10,11,9,10.0,100\n"
        "2026-01-02,CCCUSD,10,11,9,11.0,100\n"
        "2026-01-03,CCCUSD,10,11,9,12.0,100\n"
        "2026-01-02,BBBUSD,20,21,19,21.0,200\n"
        "2026-01-03,BBBUSD,20,21,19,22.0,200\n"
    )
    provider = build_provider(csv, tmp_path / "qlib_data")

    _init_qlib(provider)
    from qlib.data import D

    df = D.features(["CCCUSD", "BBBUSD"], ["$close"], freq="day")

    assert df.loc["CCCUSD"]["$close"].tolist() == pytest.approx([10.0, 11.0, 12.0])

    bbb = df.loc["BBBUSD"]["$close"]
    by_date = {ts.date(): v for ts, v in bbb.items()}
    assert by_date[date(2026, 1, 2)] == pytest.approx(21.0)
    assert by_date[date(2026, 1, 3)] == pytest.approx(22.0)
    assert math.isnan(by_date[date(2026, 1, 1)])
