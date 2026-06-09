import datetime as dt

import pytest

from cli.data.binance import kline_checksum_url, kline_zip_url, parse_checksum_file


def test_kline_zip_url_shape():
    url = kline_zip_url("BTCUSDT", "1d", dt.date(2024, 1, 2))
    assert url == ("https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-02.zip")


def test_kline_checksum_url_appends_suffix():
    url = kline_checksum_url("ETHUSDT", "1d", dt.date(2024, 1, 2))
    assert url == kline_zip_url("ETHUSDT", "1d", dt.date(2024, 1, 2)) + ".CHECKSUM"


def test_parse_checksum_file_valid():
    content = "a" * 64 + "  ETHUSDT-1d-2024-01-02.zip\n"
    assert parse_checksum_file(content) == "a" * 64


def test_parse_checksum_file_malformed_raises():
    with pytest.raises(ValueError, match="malformed"):
        parse_checksum_file("oops not a hash\n")
    with pytest.raises(ValueError, match="malformed"):
        parse_checksum_file("")
