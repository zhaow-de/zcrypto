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


def test_parse_pairs_file_uppercases_symbols(tmp_path):
    p = tmp_path / "pairs.txt"
    p.write_text("btcusdt\nETHUSDT\n  bnbusdt  \n")
    assert parse_pairs_file(p) == ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


def test_parse_pairs_file_dedupes_after_case_normalization(tmp_path):
    p = tmp_path / "pairs.txt"
    p.write_text("BTCUSDT\nbtcusdt\nBtcUsdt\n")
    assert parse_pairs_file(p) == ["BTCUSDT"]


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


# ---------------------------------------------------------------------------
# Orchestration tests (Slice 2)
# ---------------------------------------------------------------------------


from cli.data.pipeline import download_pipeline  # noqa: E402
from cli.data.verify import verify_dataset  # noqa: E402


def _seed_source(start: dt.date, end: dt.date) -> FakeSource:
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    src.add_pair("ETHUSDT", "ETH", "USDT")
    cur = start
    while cur <= end:
        src.add_kline("BTCUSDT", "1d", cur, base_price=20000.0)
        if cur >= start + dt.timedelta(days=2):  # ragged left edge for ETH
            src.add_kline("ETHUSDT", "1d", cur, base_price=1500.0)
        cur += dt.timedelta(days=1)
    return src


def test_download_fresh_writes_valid_dataset(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(
        out_dir=tmp_path / "ds",
        pairs_file=pairs,
        interval="1d",
        from_date=dt.date(2024, 1, 1),
        to_date=dt.date(2024, 1, 5),
        source=src,
    )
    report = verify_dataset(tmp_path / "ds")
    assert report.ok, report.problems
    # Ragged left edge: ETH from 2024-01-03 (start+2)
    instr = (tmp_path / "ds" / "instruments" / "all.txt").read_text(encoding="utf-8").splitlines()
    assert "BTCUSDT\t2024-01-01\t2024-01-05" in instr
    assert "ETHUSDT\t2024-01-03\t2024-01-05" in instr


def test_download_extend_appends_new_dates(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)

    # Add more days; re-run with the same --from (overlap → adjust)
    cur = dt.date(2024, 1, 6)
    while cur <= dt.date(2024, 1, 8):
        src.add_kline("BTCUSDT", "1d", cur)
        src.add_kline("ETHUSDT", "1d", cur)
        cur += dt.timedelta(days=1)
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 8), src)
    assert verify_dataset(out).ok


def test_download_gap_error(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    # Now caller asks for a from-date 2+ days past index.to → gap error.
    with pytest.raises(PipelineError, match="gap"):
        download_pipeline(out, pairs, "1d", dt.date(2024, 1, 10), dt.date(2024, 1, 12), src)


def test_download_unsupported_interval_raises(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    with pytest.raises(PipelineError, match="not supported"):
        download_pipeline(tmp_path / "ds", pairs, "1h", dt.date(2024, 1, 1), dt.date(2024, 1, 2), FakeSource())


def test_download_indexed_pair_absent_from_file_errors(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    # Drop ETH from the file → second run should error.
    pairs.write_text("BTCUSDT\n")
    with pytest.raises(PipelineError, match="absent from pairs file"):
        download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 8), src)


def test_download_checksum_mismatch_raises(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 3))
    src.tamper_kline_checksum("BTCUSDT", "1d", dt.date(2024, 1, 2))
    with pytest.raises(PipelineError, match="checksum"):
        download_pipeline(tmp_path / "ds", pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 3), src)


def test_download_leaves_live_dir_pristine_on_error(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    before = sorted((out / "features" / "btcusdt").glob("*.bin"))
    before_sizes = [p.stat().st_size for p in before]

    # Force a checksum failure on a subsequent extend → expect raise, live untouched.
    cur = dt.date(2024, 1, 6)
    while cur <= dt.date(2024, 1, 8):
        src.add_kline("BTCUSDT", "1d", cur)
        src.add_kline("ETHUSDT", "1d", cur)
        cur += dt.timedelta(days=1)
    src.tamper_kline_checksum("BTCUSDT", "1d", dt.date(2024, 1, 7))
    with pytest.raises(PipelineError):
        download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 8), src)
    after_sizes = [p.stat().st_size for p in sorted((out / "features" / "btcusdt").glob("*.bin"))]
    assert before_sizes == after_sizes
    assert verify_dataset(out).ok


def test_download_extend_contiguous_no_adjust(tmp_path):
    """`--from == index.to + 1` is the no-overlap-no-gap case; no warning needed, just continue."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)

    # Extend with --from exactly one day after index.to (contiguous branch).
    cur = dt.date(2024, 1, 6)
    while cur <= dt.date(2024, 1, 8):
        src.add_kline("BTCUSDT", "1d", cur)
        cur += dt.timedelta(days=1)
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 6), dt.date(2024, 1, 8), src)
    assert verify_dataset(out).ok
    # Calendar now spans the full union
    cal_lines = (out / "calendars" / "day.txt").read_text(encoding="utf-8").splitlines()
    assert cal_lines[0] == "2024-01-01"
    assert cal_lines[-1] == "2024-01-08"


# ---------------------------------------------------------------------------
# Concurrent fetcher tests (Slice 5)
# ---------------------------------------------------------------------------


from tests.data_fixtures import CountingSource  # noqa: E402


def test_download_fetches_concurrently_within_cap(tmp_path, monkeypatch):
    """Peak concurrent fetches stays <= CliConstants.FETCH_CONCURRENCY AND parallelism actually happens."""
    from cli.constants import CliConstants

    monkeypatch.setattr(CliConstants, "FETCH_CONCURRENCY", 3)
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    src = CountingSource(request_delay=0.05)
    src.add_pair("BTCUSDT", "BTC", "USDT")
    for d in (dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(15)):
        src.add_kline("BTCUSDT", "1d", d)
    download_pipeline(
        tmp_path / "ds",
        pairs,
        "1d",
        dt.date(2024, 1, 1),
        dt.date(2024, 1, 15),
        src,
    )
    assert src.peak_concurrent <= 3, f"expected peak <= 3, got {src.peak_concurrent}"
    assert src.peak_concurrent >= 2, f"expected concurrent fetches, peak was only {src.peak_concurrent}"
    assert src.total_requests == 15
