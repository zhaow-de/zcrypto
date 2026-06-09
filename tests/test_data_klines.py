import datetime as dt
import io
import zipfile

import pytest

from cli.data.klines import assert_no_internal_gaps, parse_kline_zip
from tests.data_fixtures import make_zip_with_checksum, synthetic_kline_csv

D = dt.date(2024, 1, 2)


def test_parse_kline_zip_no_header_one_row():
    csv = synthetic_kline_csv(D, base_price=100.0, base_vol=50.0)
    zip_bytes, _ = make_zip_with_checksum(csv, f"BTCUSDT-1d-{D}.csv")
    df = parse_kline_zip(zip_bytes, "BTCUSDT", "1d", D)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["date"] == D
    assert row["open"] == pytest.approx(100.0)
    assert row["close"] == pytest.approx(101.0)
    assert row["volume"] == pytest.approx(50.0)
    # vwap = amount/volume = (50 * (100+101)/2) / 50 = 100.5
    assert row["vwap"] == pytest.approx(100.5)
    assert row["factor"] == pytest.approx(1.0)


def test_parse_kline_zip_skips_header_row():
    header = (
        "open_time,open,high,low,close,volume,close_time,quote_asset_volume,"
        "count,taker_buy_base_volume,taker_buy_quote_volume,ignore\n"
    )
    csv = header + synthetic_kline_csv(D)
    zip_bytes, _ = make_zip_with_checksum(csv, f"BTCUSDT-1d-{D}.csv")
    df = parse_kline_zip(zip_bytes, "BTCUSDT", "1d", D)
    assert df.iloc[0]["date"] == D
    assert df.iloc[0]["open"] == pytest.approx(100.0)


def test_parse_kline_zip_zero_volume_vwap_falls_back_to_close():
    open_ms = int(dt.datetime(D.year, D.month, D.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
    close_ms = open_ms + 86_400_000 - 1
    csv = f"{open_ms},100,101,99,100.5,0,{close_ms},0,0,0,0,0\n"
    zip_bytes, _ = make_zip_with_checksum(csv, f"BTCUSDT-1d-{D}.csv")
    df = parse_kline_zip(zip_bytes, "BTCUSDT", "1d", D)
    assert df.iloc[0]["volume"] == 0
    assert df.iloc[0]["vwap"] == pytest.approx(100.5)  # = close


def test_parse_kline_zip_wrong_date_raises():
    csv = synthetic_kline_csv(D)
    zip_bytes, _ = make_zip_with_checksum(csv, f"BTCUSDT-1d-{D}.csv")
    with pytest.raises(ValueError, match="mismatch"):
        parse_kline_zip(zip_bytes, "BTCUSDT", "1d", dt.date(2024, 1, 3))


def test_parse_kline_zip_more_than_one_file_in_zip_raises():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.csv", "x")
        zf.writestr("b.csv", "x")
    with pytest.raises(ValueError, match="exactly one file"):
        parse_kline_zip(buf.getvalue(), "BTCUSDT", "1d", D)


def test_assert_no_internal_gaps_passes():
    expected = [D, D + dt.timedelta(days=1), D + dt.timedelta(days=2)]
    observed = list(expected)
    assert_no_internal_gaps(observed, expected)  # no raise


def test_assert_no_internal_gaps_raises_on_missing():
    expected = [D, D + dt.timedelta(days=1), D + dt.timedelta(days=2)]
    observed = [D, D + dt.timedelta(days=2)]
    with pytest.raises(ValueError, match="gap"):
        assert_no_internal_gaps(observed, expected)
