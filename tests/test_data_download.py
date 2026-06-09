import datetime as dt
from pathlib import Path

import pytest

from cli.data.index import load_index
from cli.data.pipeline import PipelineError, download_pipeline
from cli.data.verify import verify_dataset
from tests.data_fixtures import FakeSource


def test_download_delisted_pair_fetches_historical_range(tmp_path):
    """MATICUSDT (status=BREAK) → download fetches [first, last] archive only."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("MATICUSDT\n")
    out = tmp_path / "ds"
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    # Archive: 2020-01-01..2020-01-05 only
    for i in range(5):
        src.add_kline("MATICUSDT", "1d", dt.date(2020, 1, 1) + dt.timedelta(days=i))

    download_pipeline(out, pairs, "1d", dt.date(2019, 1, 1), dt.date(2024, 1, 1), src)

    report = verify_dataset(out)
    assert report.ok, report.problems
    idx = load_index(out)
    interval = idx.pairs["MATICUSDT"].intervals["1d"]
    assert interval.dates_from == "2020-01-01"
    assert interval.dates_to == "2020-01-05"  # last_available, NOT arg_to


def test_download_mixed_trading_and_delisted_pairs_non_uniform_to_dates(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nMATICUSDT\n")
    out = tmp_path / "ds"
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    for i in range(10):
        src.add_kline("BTCUSDT", "1d", dt.date(2024, 1, 1) + dt.timedelta(days=i))
    for i in range(5):
        src.add_kline("MATICUSDT", "1d", dt.date(2024, 1, 1) + dt.timedelta(days=i))

    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 10), src)
    idx = load_index(out)
    btc = idx.pairs["BTCUSDT"].intervals["1d"]
    mat = idx.pairs["MATICUSDT"].intervals["1d"]
    assert btc.dates_to == "2024-01-10"  # extends to arg_to
    assert mat.dates_to == "2024-01-05"  # truncated at last_available


def test_download_delisted_pair_no_archive_in_range_errors(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("MATICUSDT\n")
    out = tmp_path / "ds"
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    # No add_kline calls — pair exists in exchange_info but no archive.

    with pytest.raises(PipelineError, match=r"no kline data|status="):
        download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 10), src)
