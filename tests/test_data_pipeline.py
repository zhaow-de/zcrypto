import datetime as dt
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# Commit-phase crash recovery tests
# ---------------------------------------------------------------------------


def test_commit_failure_restores_from_snapshot(tmp_path, monkeypatch):
    """If _commit_staging raises mid-way through file moves, the live dir is rolled back from the snapshot."""
    import shutil

    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))

    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)

    initial_calendar = (out / "calendars" / "day.txt").read_text(encoding="utf-8")
    initial_index_bytes = (out / "index.json").read_bytes()

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
        download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 8), src)

    # Live state restored to pre-commit
    assert (out / "calendars" / "day.txt").read_text(encoding="utf-8") == initial_calendar
    assert (out / "index.json").read_bytes() == initial_index_bytes
    assert not (out / ".commit-in-progress").exists()
    assert verify_dataset(out).ok


def test_interrupted_commit_marker_triggers_recovery_on_next_run(tmp_path):
    """A leftover .commit-in-progress marker (simulating a killed process) is auto-resolved on next run."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))

    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)

    # Capture the good calendar bytes for the recovery check.
    good_calendar = (out / "calendars" / "day.txt").read_text(encoding="utf-8")

    # Simulate a killed process: corrupt the live calendar AND plant a marker pointing at the most recent snapshot.
    snaps = sorted((out / ".snapshots").glob("*.tar.gz"))
    assert snaps, "expected at least one snapshot from the previous download"
    (out / ".commit-in-progress").write_text(snaps[-1].name + "\n", encoding="utf-8")
    (out / "calendars" / "day.txt").write_text("CORRUPTED\n", encoding="utf-8")

    # Add one more day so the recovery run still has new work to commit.
    src.add_kline("BTCUSDT", "1d", dt.date(2024, 1, 6))

    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 6), src)

    # Marker gone; new dataset extends to 2024-01-06; calendar contains both old and new dates.
    assert not (out / ".commit-in-progress").exists()
    new_calendar = (out / "calendars" / "day.txt").read_text(encoding="utf-8")
    assert "2024-01-01" in new_calendar
    assert "2024-01-06" in new_calendar
    assert "CORRUPTED" not in new_calendar  # the corruption was overwritten by recovery + new write
    assert verify_dataset(out).ok


def test_interrupted_commit_marker_missing_snapshot_errors(tmp_path):
    """A marker pointing at a nonexistent snapshot raises PipelineError with a clear message."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 2))

    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 2), src)

    (out / ".commit-in-progress").write_text("nonexistent-snapshot.tar.gz\n", encoding="utf-8")

    with pytest.raises(PipelineError, match=r"missing|cannot auto-recover"):
        download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 2), src)


def test_verify_flags_stale_commit_marker(tmp_path):
    """verify_dataset reports a problem when a stale .commit-in-progress marker is present."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 2))
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 2), src)

    (out / ".commit-in-progress").write_text("some-snapshot.tar.gz\n", encoding="utf-8")
    report = verify_dataset(out)
    assert not report.ok
    assert any("commit-in-progress" in p for p in report.problems)


def test_download_existing_pair_delisted_mid_window_raises_actionable_error(tmp_path):
    """An existing pair whose right edge is no longer reachable triggers a clear delist/rename hint."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))

    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)

    # Simulate a mid-window delisting: re-run extending to 2024-01-08, but DON'T add the new klines.
    # The source still has the pair listed in exchange_info (so validate passes) but no klines at the right edge.
    with pytest.raises(PipelineError, match=r"delisted|rename"):
        download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 8), src)


def test_download_aborts_on_broken_pre_existing_dataset(tmp_path):
    """download_pipeline refuses to mutate a partial/broken dataset."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    out.mkdir(parents=True)
    # Seed a partial state: just calendars/, no index.json.
    (out / "calendars").mkdir()
    (out / "calendars" / "day.txt").write_text("2024-01-01\n")

    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 2))
    with pytest.raises(PipelineError, match=r"refusing to mutate|verified state"):
        download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 2), src)


def test_download_proceeds_on_empty_out_dir(tmp_path):
    """An empty out_dir is allowed — fresh download proceeds normally."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    out.mkdir(parents=True)  # exists but empty
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 2))
    # Should not raise.
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 2), src)
    assert verify_dataset(out).ok


def test_download_no_op_skips_snapshot(tmp_path):
    """If pairs.txt + dates resolve to no fetches, download is a no-op: no snapshot file added."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))

    # First download — should snapshot + commit
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    snaps_before = sorted(p.name for p in (out / ".snapshots").glob("*.tar.gz"))
    assert len(snaps_before) >= 1, "first download must take a snapshot"

    # Second download with same args → no work needed → no new snapshot
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    snaps_after = sorted(p.name for p in (out / ".snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after, (
        f"expected no new snapshot on no-op download, got new entries: {set(snaps_after) - set(snaps_before)}"
    )


def test_download_dry_run_prints_plan_no_mutation(tmp_path, capsys):
    """--dry-run skips snapshot + mutation; prints plan summary to stdout."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))

    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src, dry_run=True)

    # No dataset created, no snapshot
    assert not (out / "index.json").exists()
    snaps = list((out / ".snapshots").glob("*.tar.gz")) if (out / ".snapshots").exists() else []
    assert not snaps
    # Plan summary printed
    captured = capsys.readouterr()
    assert "DRY-RUN" in captured.out or "BTCUSDT" in captured.out


def test_download_snapshot_uses_download_cmd_name(tmp_path):
    """The snapshot tar.gz produced by a real download run is <stamp>-download.tar.gz."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 2))

    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 2), src)
    snaps = list((out / ".snapshots").glob("*-download.tar.gz"))
    assert len(snaps) == 1, (
        f"expected one snapshot named *-download.tar.gz, got: {[s.name for s in (out / '.snapshots').glob('*')]}"
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
    out = tmp_path / "ds"
    out.mkdir(parents=True)
    # Partial / broken state: components without index.json → ok=False, is_empty=False
    (out / "calendars").mkdir()
    (out / "calendars" / "day.txt").write_text("2024-01-01\n")

    plan_fn = lambda d: pytest.fail("plan_fn must not be called on broken dataset")
    apply_fn = lambda d, s, p: pytest.fail("apply_fn must not be called")

    from cli.data.pipeline import PipelineError, _execute_mutation

    with pytest.raises(PipelineError, match=r"refusing to mutate"):
        _execute_mutation(out, "fakecmd", plan_fn, apply_fn, dry_run=False)


def test_execute_mutation_dry_run_with_marker_aborts(tmp_path):
    """Dry-run errors if a .commit-in-progress marker is present (recovery would mutate)."""
    out = tmp_path / "ds"
    out.mkdir(parents=True)
    (out / ".commit-in-progress").write_text("some-snapshot.tar.gz\n")

    from cli.data.pipeline import PipelineError, _execute_mutation

    with pytest.raises(PipelineError, match=r"commit-in-progress marker"):
        _execute_mutation(
            out,
            "fakecmd",
            plan_fn=lambda d: _StubPlan(),
            apply_fn=lambda d, s, p: None,
            dry_run=True,
        )


def test_execute_mutation_noop_no_snapshot_no_marker(tmp_path):
    """No-op plan → harness logs and returns; no snapshot, no marker, no staging dir."""
    out = tmp_path / "ds"
    out.mkdir(parents=True)
    # Empty dir is allowed (is_empty=True passes pre-flight)

    from cli.data.pipeline import _execute_mutation

    _execute_mutation(
        out,
        "fakecmd",
        plan_fn=lambda d: _StubPlan(is_noop=True),
        apply_fn=lambda d, s, p: pytest.fail("apply must not be called"),
        dry_run=False,
    )
    assert not (out / ".snapshots").exists() or not list((out / ".snapshots").glob("*.tar.gz"))
    assert not (out / ".commit-in-progress").exists()
    assert not (out / ".staging").exists()


def test_execute_mutation_dry_run_prints_summary_no_side_effects(tmp_path, capsys):
    """--dry-run with a non-noop plan prints the summary; no snapshot."""
    out = tmp_path / "ds"
    out.mkdir(parents=True)

    from cli.data.pipeline import _execute_mutation

    _execute_mutation(
        out,
        "fakecmd",
        plan_fn=lambda d: _StubPlan(is_noop=False, summary="DRY-RUN: would do stuff"),
        apply_fn=lambda d, s, p: pytest.fail("apply must not run under dry-run"),
        dry_run=True,
    )
    captured = capsys.readouterr()
    assert "DRY-RUN: would do stuff" in captured.out
    assert not (out / ".snapshots").exists() or not list((out / ".snapshots").glob("*.tar.gz"))


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

    src_out = tmp_path / "src_ds"
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    for i in range(3):
        src.add_kline("BTCUSDT", "1d", dt.date(2024, 1, 1) + dt.timedelta(days=i))
    download_pipeline(src_out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 3), src)

    # Now run _execute_mutation on a fresh out_dir, apply_fn just copies the
    # known-good dataset's components into staging.
    out = tmp_path / "ds"
    out.mkdir(parents=True)

    def apply_copy(out_dir, staging, plan):
        for name in ("calendars", "instruments", "features", "index.json"):
            src_path = src_out / name
            dst_path = staging / name
            if src_path.is_dir():
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)

    _execute_mutation(
        out,
        "fakecmd",
        plan_fn=lambda d: _StubPlan(is_noop=False),
        apply_fn=apply_copy,
        dry_run=False,
    )

    assert (out / "index.json").exists()
    assert (out / "features" / "btcusdt").is_dir()
    # Snapshot exists and is named with cmd_name
    snaps = list((out / ".snapshots").glob("*-fakecmd.tar.gz"))
    assert len(snaps) == 1, f"expected one snapshot tagged with cmd_name, got {[s.name for s in (out / '.snapshots').glob('*')]}"
    # Marker cleaned up
    assert not (out / ".commit-in-progress").exists()
    assert not (out / ".staging").exists()


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
    """MATIC-shaped case: data 2020-01-01..2020-01-05; nothing later."""
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    for i in range(5):
        src.add_kline("MATICUSDT", "1d", dt.date(2020, 1, 1) + dt.timedelta(days=i))

    rng = find_available_range(src, "MATICUSDT", "1d", dt.date(2019, 1, 1), dt.date(2025, 1, 1))
    # Anchor-finding falls back to probe scan; should locate Jan 2020 cluster.
    assert rng is not None
    assert rng[0] == dt.date(2020, 1, 1)
    assert rng[1] == dt.date(2020, 1, 5)
