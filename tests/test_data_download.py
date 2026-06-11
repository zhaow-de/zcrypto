import datetime as dt
from pathlib import Path

import pytest

from cli.data.index import load_index
from cli.data.pipeline import PipelineError, download_pipeline
from cli.data.verify import verify_dataset
from tests.data_fixtures import FakeSource


def test_download_delisted_pair_fetches_historical_range(tmp_path):
    """MATICUSDT (status=BREAK) → download fetches [first, last] archive only.

    Realistic MATIC dates: traded 2019-04-26..2024-09-10 before the POL rename."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("MATICUSDT\n")
    out = tmp_path / "ds"
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    cur = dt.date(2019, 4, 26)
    while cur <= dt.date(2024, 9, 10):
        src.add_kline("MATICUSDT", "1d", cur)
        cur += dt.timedelta(days=1)

    download_pipeline(out, pairs, "1d", dt.date(2018, 1, 1), dt.date(2026, 1, 1), src)

    report = verify_dataset(out)
    assert report.ok, report.problems
    idx = load_index(out)
    interval = idx.pairs["MATICUSDT"].intervals["1d"]
    assert interval.dates_from == "2019-04-26"
    assert interval.dates_to == "2024-09-10"  # last_available, NOT arg_to


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


def test_download_new_trading_pair_publishing_lag_clips_to_last_available(tmp_path):
    """When the archive's latest day is older than arg_to (publishing lag),
    a new TRADING pair's effective_to should clip to last available, not error."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("ADAUSDT\n")
    out = tmp_path / "ds"
    src = FakeSource()
    src.add_pair("ADAUSDT", "ADA", "USDT")  # TRADING
    # Archive: 2024-01-01..2024-01-09 (no 2024-01-10 — simulated publishing lag)
    for i in range(9):
        src.add_kline("ADAUSDT", "1d", dt.date(2024, 1, 1) + dt.timedelta(days=i))

    # arg_to = 2024-01-10 (a day the archive hasn't published yet)
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 10), src)

    idx = load_index(out)
    ada = idx.pairs["ADAUSDT"].intervals["1d"]
    assert ada.dates_from == "2024-01-01"
    assert ada.dates_to == "2024-01-09"  # clipped to last available
    assert verify_dataset(out).ok
