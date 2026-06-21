import datetime as dt
from pathlib import Path

import pytest

from cli.data.layout import DatasetPaths
from cli.data.pipeline import (
    PipelineError,
    find_available_range,
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
        {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "status": "TRADING"},
        {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT", "status": "TRADING"},
    ]
    assert validate_pairs_against_exchange(["BTCUSDT", "ETHUSDT"], info) == {
        "BTCUSDT": ("BTC", "USDT", "TRADING"),
        "ETHUSDT": ("ETH", "USDT", "TRADING"),
    }


def test_validate_pairs_classifies_trading_pair():
    """A TRADING pair returns (base, quote, 'TRADING')."""
    from tests.data_fixtures import FakeSource

    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")  # default status="TRADING"

    classified = validate_pairs_against_exchange(["BTCUSDT"], src.fetch_exchange_info())
    assert classified == {"BTCUSDT": ("BTC", "USDT", "TRADING")}


def test_validate_pairs_classifies_break_pair():
    """A status=BREAK pair is returned with 'BREAK', not filtered out."""
    from tests.data_fixtures import FakeSource

    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")

    classified = validate_pairs_against_exchange(["MATICUSDT"], src.fetch_exchange_info())
    assert classified == {"MATICUSDT": ("MATIC", "USDT", "BREAK")}


def test_validate_pairs_unknown_symbol_errors():
    """An unknown symbol still errors (iter-4 behavior preserved)."""
    from tests.data_fixtures import FakeSource

    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")

    with pytest.raises(PipelineError):
        validate_pairs_against_exchange(["XYZUSDT"], src.fetch_exchange_info())


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
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(
        paths,
        pairs_file=pairs,
        interval="1d",
        from_date=dt.date(2024, 1, 1),
        to_date=dt.date(2024, 1, 5),
        source=src,
    )
    report = verify_dataset(data_dir)
    assert report.ok, report.problems
    # Ragged left edge: ETH from 2024-01-03 (start+2)
    instr = (data_dir / "instruments" / "all.txt").read_text(encoding="utf-8").splitlines()
    assert "BTCUSDT\t2024-01-01\t2024-01-05" in instr
    assert "ETHUSDT\t2024-01-03\t2024-01-05" in instr


def test_download_extend_appends_new_dates(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)

    # Add more days; re-run with the same --from (overlap → adjust)
    cur = dt.date(2024, 1, 6)
    while cur <= dt.date(2024, 1, 8):
        src.add_kline("BTCUSDT", "1d", cur)
        src.add_kline("ETHUSDT", "1d", cur)
        cur += dt.timedelta(days=1)
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 8), src)
    assert verify_dataset(data_dir).ok


def test_download_gap_error(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    # Now caller asks for a from-date 2+ days past index.to → gap error.
    with pytest.raises(PipelineError, match="gap"):
        download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 10), dt.date(2024, 1, 12), src)


def test_download_unsupported_interval_raises(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    with pytest.raises(PipelineError, match="not supported"):
        download_pipeline(paths, pairs, "1h", dt.date(2024, 1, 1), dt.date(2024, 1, 2), FakeSource())


def test_download_indexed_pair_absent_from_file_errors(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    # Drop ETH from the file → second run should error.
    pairs.write_text("BTCUSDT\n")
    with pytest.raises(PipelineError, match="absent from pairs file"):
        download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 8), src)


def test_download_checksum_mismatch_raises(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 3))
    src.tamper_kline_checksum("BTCUSDT", "1d", dt.date(2024, 1, 2))
    with pytest.raises(PipelineError, match="checksum"):
        download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 3), src)


def test_download_missing_checksum_warns_and_continues(tmp_path, caplog, monkeypatch):
    """A zip with no published .CHECKSUM is accepted via structure+parse, with a warning."""
    import logging

    monkeypatch.setattr(logging.getLogger("zcrypto"), "propagate", True)
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 3))
    src.drop_kline_checksum("BTCUSDT", "1d", dt.date(2024, 1, 2))
    with caplog.at_level(logging.WARNING):
        download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 3), src)
    assert verify_dataset(data_dir).ok
    assert any("no .CHECKSUM" in r.getMessage() for r in caplog.records)


def test_download_leaves_live_dir_pristine_on_error(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    before = sorted((data_dir / "features" / "btcusdt").glob("*.bin"))
    before_sizes = [p.stat().st_size for p in before]

    # Force a checksum failure on a subsequent extend → expect raise, live untouched.
    cur = dt.date(2024, 1, 6)
    while cur <= dt.date(2024, 1, 8):
        src.add_kline("BTCUSDT", "1d", cur)
        src.add_kline("ETHUSDT", "1d", cur)
        cur += dt.timedelta(days=1)
    src.tamper_kline_checksum("BTCUSDT", "1d", dt.date(2024, 1, 7))
    with pytest.raises(PipelineError):
        download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 8), src)
    after_sizes = [p.stat().st_size for p in sorted((data_dir / "features" / "btcusdt").glob("*.bin"))]
    assert before_sizes == after_sizes
    assert verify_dataset(data_dir).ok


# ---------------------------------------------------------------------------
# fetch_checksummed_zip (shared fetch + checksum-validate atomic)
# ---------------------------------------------------------------------------


from cli.data.pipeline import fetch_checksummed_zip  # noqa: E402


def test_fetch_checksummed_zip_matching_checksum_returns_validated():
    import hashlib

    raw = b"some-zip-bytes"
    digest = hashlib.sha256(raw).hexdigest()
    out, validated = fetch_checksummed_zip(lambda: raw, lambda: digest)
    assert out == raw
    assert validated is True


def test_fetch_checksummed_zip_mismatch_raises():
    raw = b"some-zip-bytes"
    with pytest.raises(PipelineError, match="checksum"):
        fetch_checksummed_zip(lambda: raw, lambda: "0" * 64)


def test_fetch_checksummed_zip_absent_checksum_returns_unvalidated():
    raw = b"some-zip-bytes"
    out, validated = fetch_checksummed_zip(lambda: raw, lambda: None)
    assert out == raw
    assert validated is False


def test_download_extend_contiguous_no_adjust(tmp_path):
    """`--from == index.to + 1` is the no-overlap-no-gap case; no warning needed, just continue."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)

    # Extend with --from exactly one day after index.to (contiguous branch).
    cur = dt.date(2024, 1, 6)
    while cur <= dt.date(2024, 1, 8):
        src.add_kline("BTCUSDT", "1d", cur)
        cur += dt.timedelta(days=1)
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 6), dt.date(2024, 1, 8), src)
    assert verify_dataset(data_dir).ok
    # Calendar now spans the full union
    cal_lines = (data_dir / "calendars" / "day.txt").read_text(encoding="utf-8").splitlines()
    assert cal_lines[0] == "2024-01-01"
    assert cal_lines[-1] == "2024-01-08"


# ---------------------------------------------------------------------------
# Funding write tests (iter-15 Task 3)
# ---------------------------------------------------------------------------


import math  # noqa: E402

from cli.data.qlib_writer import read_bin  # noqa: E402


def test_download_writes_funding_bin_aligned_to_calendar(tmp_path):
    """download writes features/<inst>/funding.day.bin aligned to the kline calendar.

    The synthetic funding zip puts three settlements (0.0001+0.0002+0.0003 = 0.0006)
    on day 1 of each month and nothing else, so day-1 funding == 0.0006 and every
    other day in the month is absent (NaN)."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    data_dir = tmp_path / "data"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=tmp_path / "bk")

    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    for d in (dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(4)):
        src.add_kline("BTCUSDT", "1d", d, base_price=20000.0)
    src.add_funding("BTCUSDT", 2024, 1)  # day-1 funding == 0.0006, days 2-4 absent

    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 4), src)
    assert verify_dataset(data_dir).ok

    start_idx, values = read_bin(data_dir / "features" / "btcusdt" / "funding.day.bin")
    assert start_idx == 0  # same start_index as the kline bins (calendar starts 2024-01-01)
    _, close_values = read_bin(data_dir / "features" / "btcusdt" / "close.day.bin")
    assert len(values) == len(close_values)  # same row count as the kline bins
    assert values[0] == pytest.approx(0.0006)  # 2024-01-01: sum of the three settlements
    assert all(math.isnan(v) for v in values[1:])  # 2024-01-02..04 absent → NaN


def test_download_funding_starts_late_has_nan_early(tmp_path):
    """A pair whose funding archive starts in a later month than its klines has the
    early (pre-funding) dates absent/NaN, aligned to the same calendar."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    data_dir = tmp_path / "data"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=tmp_path / "bk")

    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    # Klines span Jan→Feb 2024; funding archive only exists for February.
    cur = dt.date(2024, 1, 30)
    while cur <= dt.date(2024, 2, 2):
        src.add_kline("BTCUSDT", "1d", cur, base_price=20000.0)
        cur += dt.timedelta(days=1)
    src.add_funding("BTCUSDT", 2024, 2)  # Jan archive is a 404 (not registered)

    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 30), dt.date(2024, 2, 2), src)
    assert verify_dataset(data_dir).ok

    start_idx, values = read_bin(data_dir / "features" / "btcusdt" / "funding.day.bin")
    assert start_idx == 0
    # Calendar: 2024-01-30, 01-31, 02-01, 02-02.
    assert math.isnan(values[0])  # 2024-01-30 — no Jan archive
    assert math.isnan(values[1])  # 2024-01-31 — no Jan archive
    assert values[2] == pytest.approx(0.0006)  # 2024-02-01 — three Feb settlements
    assert math.isnan(values[3])  # 2024-02-02 — absent within Feb archive


# ---------------------------------------------------------------------------
# Concurrent fetcher tests (Slice 5)
# ---------------------------------------------------------------------------


from tests.data_fixtures import CountingSource  # noqa: E402


def test_download_fetches_concurrently_within_cap(tmp_path):
    """Peak concurrent fetches stays <= the injected fetch_concurrency AND parallelism actually happens."""
    from cli.config import FetchConfig

    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = CountingSource(request_delay=0.05)
    src.add_pair("BTCUSDT", "BTC", "USDT")
    for d in (dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(15)):
        src.add_kline("BTCUSDT", "1d", d)
    download_pipeline(
        paths,
        pairs,
        "1d",
        dt.date(2024, 1, 1),
        dt.date(2024, 1, 15),
        src,
        fetch=FetchConfig(fetch_concurrency=3),
    )
    assert src.peak_concurrent <= 3, f"expected peak <= 3, got {src.peak_concurrent}"
    assert src.peak_concurrent >= 2, f"expected concurrent fetches, peak was only {src.peak_concurrent}"
    assert src.total_requests == 15


# ---------------------------------------------------------------------------
# Commit-phase crash recovery tests
# ---------------------------------------------------------------------------


def test_commit_failure_restores_from_snapshot(tmp_path, monkeypatch):
    """If _commit_staging raises mid-way through file moves, the live dir is rolled back from the snapshot."""
    import shutil

    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))

    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)

    initial_calendar = (data_dir / "calendars" / "day.txt").read_text(encoding="utf-8")
    initial_index_bytes = (data_dir / "index.json").read_bytes()

    # Add more days so a follow-up run has work to do.
    cur = dt.date(2024, 1, 6)
    while cur <= dt.date(2024, 1, 8):
        src.add_kline("BTCUSDT", "1d", cur)
        src.add_kline("ETHUSDT", "1d", cur)
        cur += dt.timedelta(days=1)

    # Inject a failure into the move loop (boom on the second move — after `calendars/` already swapped).
    real_move = shutil.move
    counter = {"n": 0}

    def boom_after_first(src_arg, dst_arg, *a, **kw):
        counter["n"] += 1
        if counter["n"] == 2:
            raise OSError("simulated mid-commit disk error")
        return real_move(src_arg, dst_arg, *a, **kw)

    monkeypatch.setattr("cli.data.pipeline._shutil.move", boom_after_first)

    with pytest.raises((OSError, PipelineError)):
        download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 8), src)

    # Live state restored to pre-commit
    assert (data_dir / "calendars" / "day.txt").read_text(encoding="utf-8") == initial_calendar
    assert (data_dir / "index.json").read_bytes() == initial_index_bytes
    assert not (data_dir / ".commit-in-progress").exists()
    assert verify_dataset(data_dir).ok


def test_interrupted_commit_marker_triggers_recovery_on_next_run(tmp_path):
    """A leftover .commit-in-progress marker (simulating a killed process) is auto-resolved on next run."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))

    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)

    # Capture the good calendar bytes for the recovery check.
    good_calendar = (data_dir / "calendars" / "day.txt").read_text(encoding="utf-8")

    # Simulate a killed process: corrupt the live calendar AND plant a marker pointing at the most recent snapshot.
    snaps = sorted((backup_dir / "snapshots").glob("*.tar.gz"))
    assert snaps, "expected at least one snapshot from the previous download"
    (data_dir / ".commit-in-progress").write_text(snaps[-1].name + "\n", encoding="utf-8")
    (data_dir / "calendars" / "day.txt").write_text("CORRUPTED\n", encoding="utf-8")

    # Add one more day so the recovery run still has new work to commit.
    src.add_kline("BTCUSDT", "1d", dt.date(2024, 1, 6))

    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 6), src)

    # Marker gone; new dataset extends to 2024-01-06; calendar contains both old and new dates.
    assert not (data_dir / ".commit-in-progress").exists()
    new_calendar = (data_dir / "calendars" / "day.txt").read_text(encoding="utf-8")
    assert "2024-01-01" in new_calendar
    assert "2024-01-06" in new_calendar
    assert "CORRUPTED" not in new_calendar  # the corruption was overwritten by recovery + new write
    assert verify_dataset(data_dir).ok


def test_interrupted_commit_marker_missing_snapshot_errors(tmp_path):
    """A marker pointing at a nonexistent snapshot raises PipelineError with a clear message."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 2))

    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 2), src)

    (data_dir / ".commit-in-progress").write_text("nonexistent-snapshot.tar.gz\n", encoding="utf-8")

    with pytest.raises(PipelineError, match=r"missing|cannot auto-recover"):
        download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 2), src)


def test_verify_flags_stale_commit_marker(tmp_path):
    """verify_dataset reports a problem when a stale .commit-in-progress marker is present."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 2))
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 2), src)

    (data_dir / ".commit-in-progress").write_text("some-snapshot.tar.gz\n", encoding="utf-8")
    report = verify_dataset(data_dir)
    assert not report.ok
    assert any("commit-in-progress" in p for p in report.problems)


def test_download_existing_pair_delisted_mid_window_raises_actionable_error(tmp_path):
    """An existing pair whose right edge is no longer reachable triggers a clear delist/rename hint."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))

    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)

    # Simulate a mid-window delisting: re-run extending to 2024-02-01 (27-day gap > 7-day grace),
    # but DON'T add the new klines.
    # The source still has the pair listed in exchange_info (so validate passes) but no klines at the right edge.
    with pytest.raises(PipelineError, match=r"delisted|renamed"):
        download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 2, 1), src)


def test_download_aborts_on_broken_pre_existing_dataset(tmp_path):
    """download_pipeline refuses to mutate a partial/broken dataset."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    data_dir.mkdir(parents=True)
    # Seed a partial state: just calendars/, no index.json.
    (data_dir / "calendars").mkdir()
    (data_dir / "calendars" / "day.txt").write_text("2024-01-01\n")

    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 2))
    with pytest.raises(PipelineError, match=r"refusing to mutate|verified state"):
        download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 2), src)


def test_download_proceeds_on_empty_out_dir(tmp_path):
    """An empty data_dir is allowed — fresh download proceeds normally."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    data_dir.mkdir(parents=True)  # exists but empty
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 2))
    # Should not raise.
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 2), src)
    assert verify_dataset(data_dir).ok


def test_download_no_op_skips_snapshot(tmp_path):
    """If pairs.txt + dates resolve to no fetches, download is a no-op: no snapshot file added."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))

    # First download — should snapshot + commit
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    snaps_before = sorted(p.name for p in (backup_dir / "snapshots").glob("*.tar.gz"))
    assert len(snaps_before) >= 1, "first download must take a snapshot"

    # Second download with same args → no work needed → no new snapshot
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    snaps_after = sorted(p.name for p in (backup_dir / "snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after, (
        f"expected no new snapshot on no-op download, got new entries: {set(snaps_after) - set(snaps_before)}"
    )


def test_download_dry_run_prints_plan_no_mutation(tmp_path, capsys):
    """--dry-run skips snapshot + mutation; prints plan summary to stdout."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))

    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src, dry_run=True)

    # No dataset created, no snapshot
    assert not (data_dir / "index.json").exists()
    snaps = list((backup_dir / "snapshots").glob("*.tar.gz")) if (backup_dir / "snapshots").exists() else []
    assert not snaps
    # Plan summary printed
    captured = capsys.readouterr()
    assert "DRY-RUN" in captured.out or "BTCUSDT" in captured.out


def test_download_snapshot_uses_download_cmd_name(tmp_path):
    """The snapshot tar.gz produced by a real download run is <stamp>-download.tar.gz."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 2))

    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 2), src)
    snaps = list((backup_dir / "snapshots").glob("*-download.tar.gz"))
    assert len(snaps) == 1, (
        f"expected one snapshot named *-download.tar.gz, got: {[s.name for s in (backup_dir / 'snapshots').glob('*')]}"
    )


# ---------------------------------------------------------------------------
# _execute_mutation harness tests
# ---------------------------------------------------------------------------


class _StubPlan:
    """Test-only Plan with controllable noop/summary."""

    def __init__(self, *, is_noop: bool = False, summary: str = "(stub)"):
        self.is_noop = is_noop
        self._summary = summary

    def dry_run_summary(self) -> str:
        return self._summary


def test_execute_mutation_pre_flight_fails_aborts_with_pipeline_error(tmp_path):
    """If verify_dataset returns ok=False (and is_empty=False), harness raises before plan_fn runs."""
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    data_dir.mkdir(parents=True)
    # Partial / broken state: components without index.json → ok=False, is_empty=False
    (data_dir / "calendars").mkdir()
    (data_dir / "calendars" / "day.txt").write_text("2024-01-01\n")

    plan_fn = lambda d: pytest.fail("plan_fn must not be called on broken dataset")
    apply_fn = lambda p, s, pl: pytest.fail("apply_fn must not be called")

    from cli.data.pipeline import PipelineError, _execute_mutation

    with pytest.raises(PipelineError, match=r"refusing to mutate"):
        _execute_mutation(paths, "fakecmd", plan_fn, apply_fn, dry_run=False)


def test_execute_mutation_dry_run_with_marker_aborts(tmp_path):
    """Dry-run errors if a .commit-in-progress marker is present (recovery would mutate)."""
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    data_dir.mkdir(parents=True)
    (data_dir / ".commit-in-progress").write_text("some-snapshot.tar.gz\n")

    from cli.data.pipeline import PipelineError, _execute_mutation

    with pytest.raises(PipelineError, match=r"commit-in-progress marker"):
        _execute_mutation(
            paths,
            "fakecmd",
            plan_fn=lambda d: _StubPlan(),
            apply_fn=lambda p, s, pl: None,
            dry_run=True,
        )


def test_execute_mutation_noop_no_snapshot_no_marker(tmp_path):
    """No-op plan → harness logs and returns; no snapshot, no marker, no staging dir."""
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    data_dir.mkdir(parents=True)
    # Empty dir is allowed (is_empty=True passes pre-flight)

    from cli.data.pipeline import _execute_mutation

    _execute_mutation(
        paths,
        "fakecmd",
        plan_fn=lambda d: _StubPlan(is_noop=True),
        apply_fn=lambda p, s, pl: pytest.fail("apply must not be called"),
        dry_run=False,
    )
    assert not (backup_dir / "snapshots").exists() or not list((backup_dir / "snapshots").glob("*.tar.gz"))
    assert not (data_dir / ".commit-in-progress").exists()
    assert not (data_dir / ".staging").exists()


def test_execute_mutation_dry_run_prints_summary_no_side_effects(tmp_path, capsys):
    """--dry-run with a non-noop plan prints the summary; no snapshot."""
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    data_dir.mkdir(parents=True)

    from cli.data.pipeline import _execute_mutation

    _execute_mutation(
        paths,
        "fakecmd",
        plan_fn=lambda d: _StubPlan(is_noop=False, summary="DRY-RUN: would do stuff"),
        apply_fn=lambda p, s, pl: pytest.fail("apply must not run under dry-run"),
        dry_run=True,
    )
    captured = capsys.readouterr()
    assert "DRY-RUN: would do stuff" in captured.out
    assert not (backup_dir / "snapshots").exists() or not list((backup_dir / "snapshots").glob("*.tar.gz"))


def test_execute_mutation_real_run_invokes_apply_and_commits(tmp_path):
    """Real run: apply_fn writes a minimal valid dataset into staging; harness commits it.

    Uses _execute_mutation directly with an apply_fn that copies the iter-4 download output
    (built via a quick download_pipeline call) into staging — sidesteps re-implementing the
    full staging-build in this test.
    """
    # Build a known-good dataset first via the iter-4 download path.
    import shutil

    from cli.data.pipeline import _execute_mutation, download_pipeline
    from tests.data_fixtures import FakeSource

    src_data = tmp_path / "src_data"
    src_paths = DatasetPaths(data_dir=src_data, backup_dir=tmp_path / "src_bk")
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    for i in range(3):
        src.add_kline("BTCUSDT", "1d", dt.date(2024, 1, 1) + dt.timedelta(days=i))
    download_pipeline(src_paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 3), src)

    # Now run _execute_mutation on a fresh data_dir, apply_fn just copies the
    # known-good dataset's components into staging.
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    data_dir.mkdir(parents=True)

    def apply_copy(paths, staging, plan):
        for name in ("calendars", "instruments", "features", "index.json"):
            src_path = src_data / name
            dst_path = staging / name
            if src_path.is_dir():
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)

    _execute_mutation(
        paths,
        "fakecmd",
        plan_fn=lambda d: _StubPlan(is_noop=False),
        apply_fn=apply_copy,
        dry_run=False,
    )

    assert (data_dir / "index.json").exists()
    assert (data_dir / "features" / "btcusdt").is_dir()
    # Snapshot exists and is named with cmd_name
    snaps = list((backup_dir / "snapshots").glob("*-fakecmd.tar.gz"))
    assert len(snaps) == 1, (
        f"expected one snapshot tagged with cmd_name, got {[s.name for s in (backup_dir / 'snapshots').glob('*')]}"
    )
    # Marker cleaned up
    assert not (data_dir / ".commit-in-progress").exists()
    assert not (data_dir / ".staging").exists()


# ---------------------------------------------------------------------------
# find_available_range tests (Task 4)
# ---------------------------------------------------------------------------


def test_find_available_range_finds_first_and_last():
    """A pair with data on [2024-09-13, 2024-09-15] returns that exact range."""
    src = FakeSource()
    src.add_pair("POLUSDT", "POL", "USDT")
    for d in (dt.date(2024, 9, 13), dt.date(2024, 9, 14), dt.date(2024, 9, 15)):
        src.add_kline("POLUSDT", "1d", d)

    rng = find_available_range(src, "POLUSDT", "1d", dt.date(2024, 9, 10), dt.date(2024, 9, 20))
    assert rng == (dt.date(2024, 9, 13), dt.date(2024, 9, 15))


def test_find_available_range_no_data_returns_none():
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    # no add_kline calls

    assert find_available_range(src, "MATICUSDT", "1d", dt.date(2020, 1, 1), dt.date(2024, 12, 31)) is None


def test_find_available_range_lo_gt_hi_returns_none():
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    src.add_kline("BTCUSDT", "1d", dt.date(2024, 1, 1))

    assert find_available_range(src, "BTCUSDT", "1d", dt.date(2024, 1, 5), dt.date(2024, 1, 1)) is None


def test_find_available_range_single_day_with_data():
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    src.add_kline("BTCUSDT", "1d", dt.date(2024, 1, 1))

    rng = find_available_range(src, "BTCUSDT", "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 1))
    assert rng == (dt.date(2024, 1, 1), dt.date(2024, 1, 1))


def test_find_available_range_delisted_pair_finds_historical():
    """MATIC-shaped case: real Binance MATIC traded 2019-04-26..2024-09-10
    before the POL rename. Search window straddles both ends. The dual-direction
    doubling anchor finder should hit the data block during the backward pass
    from `hi` within ~10 probes."""
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    cur = dt.date(2019, 4, 26)
    while cur <= dt.date(2024, 9, 10):
        src.add_kline("MATICUSDT", "1d", cur)
        cur += dt.timedelta(days=1)

    rng = find_available_range(src, "MATICUSDT", "1d", dt.date(2018, 1, 1), dt.date(2026, 6, 9))
    assert rng is not None
    assert rng[0] == dt.date(2019, 4, 26)
    assert rng[1] == dt.date(2024, 9, 10)


def test_find_available_range_late_start_pair_uses_bisect_not_linear_scan(monkeypatch):
    """APT-shaped case: TRADING pair listed years after arg_from, with publishing
    lag on the right edge. Both endpoints (2020-01-01 and 2026-06-09) are 404; the
    data block is [2022-10-19, 2026-06-08]. The interior-anchor finder must use
    recursive midpoint bisect (~O(log²N) worst-case probes), NOT a day-by-day
    linear scan (which would do ~1000 probes before the first hit)."""
    src = FakeSource()
    src.add_pair("APTUSDT", "APT", "USDT")
    cur = dt.date(2022, 10, 19)
    while cur <= dt.date(2026, 6, 8):
        src.add_kline("APTUSDT", "1d", cur)
        cur += dt.timedelta(days=1)

    # Wrap exists_kline to count HEAD-equivalent probes.
    probes: list[dt.date] = []
    real_exists = src.exists_kline

    def counting_exists(symbol, interval, date):
        probes.append(date)
        return real_exists(symbol, interval, date)

    monkeypatch.setattr(src, "exists_kline", counting_exists)

    rng = find_available_range(src, "APTUSDT", "1d", dt.date(2020, 1, 1), dt.date(2026, 6, 9))
    assert rng is not None
    assert rng[0] == dt.date(2022, 10, 19)  # first available = listing date
    assert rng[1] == dt.date(2026, 6, 8)  # last available = day before publishing-lag
    # A day-by-day linear scan would do (2022-10-19 - 2020-01-01).days = 1022+ probes
    # before the first hit. The bisect-based finder must do far fewer.
    assert len(probes) < 50, (
        f"expected far fewer than 50 probes via bisect; got {len(probes)} — "
        "this suggests the day-by-day linear scan regressed back in"
    )


def test_find_available_range_arb_shaped_mid_window_listing_does_not_degrade_to_linear(monkeypatch):
    """ARB-shaped regression: data block [2023-03-23..2026-06-08] inside search
    window [2020-01-01..2026-06-09]. The midpoint (2023-03-21) lands just two
    days before the listing date — the previous recursive midpoint bisect
    degraded to ~1175 sequential probes in the no-data left half before finding
    the right half. Dual-direction doubling must catch the data block during
    the backward pass from `hi` in O(log N) probes."""
    src = FakeSource()
    src.add_pair("ARBUSDT", "ARB", "USDT")  # TRADING
    cur = dt.date(2023, 3, 23)
    while cur <= dt.date(2026, 6, 8):
        src.add_kline("ARBUSDT", "1d", cur)
        cur += dt.timedelta(days=1)

    probes: list[dt.date] = []
    real_exists = src.exists_kline

    def counting_exists(symbol, interval, date):
        probes.append(date)
        return real_exists(symbol, interval, date)

    monkeypatch.setattr(src, "exists_kline", counting_exists)

    rng = find_available_range(src, "ARBUSDT", "1d", dt.date(2020, 1, 1), dt.date(2026, 6, 9))
    assert rng is not None
    assert rng[0] == dt.date(2023, 3, 23)  # listing date
    assert rng[1] == dt.date(2026, 6, 8)  # one day before publishing-lag boundary
    # The previous recursive bisect did ~1200 probes for this shape. The dual-
    # direction doubling should hit `hi - 1 = 2026-06-08` immediately, then do
    # ~11 probes for first-available bisect.
    assert len(probes) < 40, (
        f"expected ≤ 40 probes via dual-direction doubling; got {len(probes)} — "
        "this suggests the algorithm regressed back to the recursive bisect that "
        "exhausted the no-data left half on ARB-shaped pairs"
    )


# ---------------------------------------------------------------------------
# --allow-interior-gaps tests (iter-16 Task 3)
# ---------------------------------------------------------------------------


def _seed_interior_gap_source() -> FakeSource:
    """A pair listed contiguously [2024-01-01..2024-01-05] EXCEPT an interior 404 at 2024-01-03.

    Endpoints (01-01, 01-05) and 01-02, 01-04 have klines; 01-03 has none, so
    `find_available_range` resolves [2024-01-01, 2024-01-05] and 2024-01-03 is a
    strictly-interior missing date that 404s during the fetch."""
    src = FakeSource()
    src.add_pair("FTTUSDT", "FTT", "USDT")
    for d in (dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(5)):
        if d == dt.date(2024, 1, 3):
            continue  # interior gap — no kline
        src.add_kline("FTTUSDT", "1d", d, base_price=20.0)
    return src


def test_download_interior_gap_filled_with_nan_when_flag_set(tmp_path, caplog, monkeypatch):
    """With allow_interior_gaps=True, an interior 404 becomes a NaN suspension row + a warning."""
    import logging

    monkeypatch.setattr(logging.getLogger("zcrypto"), "propagate", True)
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("FTTUSDT\n")
    data_dir = tmp_path / "data"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=tmp_path / "bk")
    src = _seed_interior_gap_source()

    with caplog.at_level(logging.WARNING):
        download_pipeline(
            paths,
            pairs,
            "1d",
            dt.date(2024, 1, 1),
            dt.date(2024, 1, 5),
            src,
            allow_interior_gaps=True,
        )

    assert verify_dataset(data_dir).ok
    # Pair spans its full [from, to] (the gap day is included, not truncated).
    instr = (data_dir / "instruments" / "all.txt").read_text(encoding="utf-8").splitlines()
    assert "FTTUSDT\t2024-01-01\t2024-01-05" in instr
    # The gap day (offset 2 → 2024-01-03) is NaN; the other days are real.
    start_idx, close_values = read_bin(data_dir / "features" / "fttusdt" / "close.day.bin")
    assert start_idx == 0
    assert len(close_values) == 5
    assert math.isnan(close_values[2])  # 2024-01-03 — synthetic NaN suspension row
    assert not math.isnan(close_values[0])  # 2024-01-01 — real data
    assert not math.isnan(close_values[4])  # 2024-01-05 — real data
    # A per-gap warning was logged.
    assert any("2024-01-03" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def test_download_interior_gap_hard_errors_without_flag(tmp_path):
    """Without the flag (default), the same interior 404 still hard-errors — unchanged behavior."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("FTTUSDT\n")
    data_dir = tmp_path / "data"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=tmp_path / "bk")
    src = _seed_interior_gap_source()

    # The hard error is the SAME interior 404 (2024-01-03) the flag-on test fills.
    with pytest.raises(PipelineError, match="2024-01-03"):
        download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
