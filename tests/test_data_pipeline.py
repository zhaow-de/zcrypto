import datetime as dt
from pathlib import Path

import pytest

from cli.data.pipeline import (
    PipelineError,
    find_first_available,
    parse_pairs_file,
    validate_pairs_against_exchange,
)
from tests.data_fixtures import FakeSource


def test_parse_pairs_file_returns_unique_nonblank_lines(tmp_path):
    p = tmp_path / "pairs.txt"
    p.write_text("BTCUSDT\n\nETHUSDT\nBTCUSDT\n\n")
    assert parse_pairs_file(p) == ["BTCUSDT", "ETHUSDT"]


def test_parse_pairs_file_missing_file_raises(tmp_path):
    with pytest.raises(PipelineError, match="does not exist"):
        parse_pairs_file(tmp_path / "missing.txt")


def test_parse_pairs_file_empty_or_blank_raises(tmp_path):
    p = tmp_path / "pairs.txt"
    p.write_text("\n\n\n")
    with pytest.raises(PipelineError, match="no symbols"):
        parse_pairs_file(p)


def test_validate_pairs_against_exchange_returns_base_quote_map():
    info = [
        {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"},
        {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT"},
    ]
    assert validate_pairs_against_exchange(["BTCUSDT", "ETHUSDT"], info) == {
        "BTCUSDT": ("BTC", "USDT"),
        "ETHUSDT": ("ETH", "USDT"),
    }


def test_validate_pairs_against_exchange_unknown_raises():
    info = [{"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"}]
    with pytest.raises(PipelineError, match="WHATUSDT"):
        validate_pairs_against_exchange(["BTCUSDT", "WHATUSDT"], info)


def test_find_first_available_finds_start_of_listing():
    src = FakeSource()
    listing_start = dt.date(2024, 1, 5)
    for d in (listing_start + dt.timedelta(days=i) for i in range(10)):
        src.add_kline("XYZUSDT", "1d", d)
    found = find_first_available(src, "XYZUSDT", "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 14))
    assert found == listing_start


def test_find_first_available_returns_none_when_window_predates_listing():
    src = FakeSource()
    assert find_first_available(src, "ZZZUSDT", "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 14)) is None


def test_find_first_available_skips_search_when_lo_exists():
    src = FakeSource()
    for d in (dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(5)):
        src.add_kline("ABCUSDT", "1d", d)
    found = find_first_available(src, "ABCUSDT", "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    assert found == dt.date(2024, 1, 1)
