import pytest

from cli.example.dataset import build_provider


def test_build_provider_roundtrip(tmp_path):
    csv = tmp_path / "toy.csv"
    csv.write_text(
        "date,symbol,open,high,low,close,volume\n"
        "2026-01-01,AAAUSD,10,11,9,10.5,100\n"
        "2026-01-02,AAAUSD,10.5,12,10,11.5,120\n"
        "2026-01-03,AAAUSD,11.5,12,11,11.0,90\n"
    )
    provider = build_provider(csv, tmp_path / "qlib_data")

    import qlib
    from qlib.constant import REG_US
    from qlib.data import D

    qlib.init(provider_uri=provider, region=REG_US)
    df = D.features(["AAAUSD"], ["$close", "$open", "$volume"], freq="day")

    assert df["$close"].tolist() == pytest.approx([10.5, 11.5, 11.0])
    assert df["$open"].tolist() == pytest.approx([10.0, 10.5, 11.5])
    assert df["$volume"].tolist() == pytest.approx([100.0, 120.0, 90.0])
