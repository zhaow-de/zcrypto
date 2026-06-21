"""Tests for cli/data/scripts/acquire_old_luna.py — FakeSource only, no network.

Iter-18: one-off acquire_old_luna script for the Terra blow-up.

The script has two phases:
  Phase 1: Insert capped old-LUNA as LUNAUSDT (via _build_staging + _execute_mutation).
  Phase 2: rename_pipeline(LUNAUSDT → LUNCUSDT) which appends NaN gap up to LUNC's
           first archive date minus one day; does NOT fetch LUNC tail klines
           (that is left to the routine backfill flow).

All tests use synthetic dates in 2024 so the test suite stays fast and network-free.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import pytest

from cli.data.index import load_index
from cli.data.layout import DatasetPaths
from cli.data.pipeline import download_pipeline
from cli.data.qlib_writer import read_bin
from cli.data.verify import verify_dataset
from tests.data_fixtures import FakeSource

# ---------------------------------------------------------------------------
# Synthetic scenario constants
# ---------------------------------------------------------------------------

# Base pair covers the full window so the calendar is always well-defined.
_BTC_FROM = dt.date(2024, 1, 1)
_BTC_TO = dt.date(2024, 1, 10)

# Old-LUNA klines: [2024-01-01, 2024-01-04] — "crash cap" = 2024-01-04.
_LUNA_OLD_FROM = dt.date(2024, 1, 1)
_LUNA_OLD_TO = dt.date(2024, 1, 4)  # inclusive — the "crash cap" date

# Luna 2.0 klines on the reused LUNAUSDT symbol: [2024-01-08, 2024-01-10].
# The script MUST NOT fetch these.
_LUNA2_FROM = dt.date(2024, 1, 8)
_LUNA2_TO = dt.date(2024, 1, 10)
_LUNA2_BASE_PRICE = 999.0  # distinctive sentinel — if this appears in LUNCUSDT bins it's a bug

# LUNCUSDT (Luna Classic) tail: [2024-01-07, 2024-01-10].
_LUNC_FROM = dt.date(2024, 1, 7)
_LUNC_TO = dt.date(2024, 1, 10)
_LUNC_BASE_PRICE = 0.0001  # distinct from old-LUNA and Luna-2.0 prices

# Synthetic cap for tests (maps to real 2022-05-13).
_TEST_CAP = dt.date(2024, 1, 4)

# After rename Variant 1, LUNCUSDT.to_date = LUNC_first - 1 = 2024-01-07 - 1 = 2024-01-06.
# The LUNC tail is NOT fetched by rename — that stays for backfill.
_EXPECTED_LUNC_TO = _LUNC_FROM - dt.timedelta(days=1)  # 2024-01-06


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_base_dataset(tmp_path: Path) -> tuple[DatasetPaths, FakeSource]:
    """Seed a single-pair (BTC) base dataset; add LUNA/LUNC data to FakeSource.

    Returns (paths, src) ready for acquire_old_luna calls.
    """
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")

    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    src.add_pair("LUNAUSDT", "LUNA", "USDT")
    src.add_pair("LUNCUSDT", "LUNC", "USDT")

    # BTC: covers the full window.
    cur = _BTC_FROM
    while cur <= _BTC_TO:
        src.add_kline("BTCUSDT", "1d", cur)
        cur += dt.timedelta(days=1)

    # Old LUNA (2024-01-01..2024-01-04).
    cur = _LUNA_OLD_FROM
    while cur <= _LUNA_OLD_TO:
        src.add_kline("LUNAUSDT", "1d", cur, base_price=100.0)
        cur += dt.timedelta(days=1)

    # Luna 2.0 on the reused LUNAUSDT symbol (2024-01-08..2024-01-10).
    # The script MUST NOT fetch these (they are beyond the cap).
    cur = _LUNA2_FROM
    while cur <= _LUNA2_TO:
        src.add_kline("LUNAUSDT", "1d", cur, base_price=_LUNA2_BASE_PRICE)
        cur += dt.timedelta(days=1)

    # LUNC tail (2024-01-07..2024-01-10).
    cur = _LUNC_FROM
    while cur <= _LUNC_TO:
        src.add_kline("LUNCUSDT", "1d", cur, base_price=_LUNC_BASE_PRICE)
        cur += dt.timedelta(days=1)

    # Build the base dataset with only BTC.
    download_pipeline(paths, pairs, "1d", _BTC_FROM, _BTC_TO, src)

    return paths, src


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_acquire_old_luna_basic(tmp_path: Path) -> None:
    """First run: LUNCUSDT appears in index; LUNAUSDT is gone; data is verified."""
    from cli.data.scripts.acquire_old_luna import acquire_old_luna

    paths, src = _seed_base_dataset(tmp_path)
    mirror_root = paths.backup_dir / "raw"

    result = acquire_old_luna(paths, src, cap=_TEST_CAP, mirror_root=mirror_root)

    idx = load_index(paths.data_dir)
    assert idx is not None

    # LUNCUSDT must be present; LUNAUSDT must be gone.
    assert "LUNCUSDT" in idx.pairs, "LUNCUSDT must be in the index after acquisition"
    assert "LUNAUSDT" not in idx.pairs, "LUNAUSDT must be removed from the index after rename"

    # from_date == old-LUNA's first day.
    lunc = idx.pairs["LUNCUSDT"].intervals["1d"]
    assert lunc.from_date == _LUNA_OLD_FROM.isoformat(), f"LUNCUSDT.from_date should be {_LUNA_OLD_FROM}, got {lunc.from_date}"

    # to_date: rename Variant 1 stops at LUNC_first - 1 = 2024-01-06.
    # The LUNC tail (2024-01-07..2024-01-10) is NOT fetched by rename_pipeline;
    # that is left to the routine backfill flow.
    assert lunc.to_date == _EXPECTED_LUNC_TO.isoformat(), (
        f"LUNCUSDT.to_date should be {_EXPECTED_LUNC_TO} (= LUNC_first - 1), got {lunc.to_date}"
    )

    # Dataset passes verify.
    report = verify_dataset(paths.data_dir)
    assert report.ok, f"verify_dataset failed after acquisition: {report.problems}"

    # Result dict includes a status.
    assert "status" in result


def test_acquire_old_luna_cap_exclusion(tmp_path: Path) -> None:
    """The script must fetch NO old-LUNA kline beyond the cap date.

    We verify this by checking the close bin: at the cap date (2024-01-04) the value
    should reflect the old-LUNA base_price (100.0 * 1.01 = 101.0), and there must
    be NO close value that equals the Luna-2.0 sentinel (999.0 * 1.01 = 999.99).
    """
    from cli.data.scripts.acquire_old_luna import acquire_old_luna

    paths, src = _seed_base_dataset(tmp_path)
    mirror_root = paths.backup_dir / "raw"

    acquire_old_luna(paths, src, cap=_TEST_CAP, mirror_root=mirror_root)

    luncusdt_close = paths.data_dir / "features" / "luncusdt" / "close.day.bin"
    assert luncusdt_close.exists(), "close.day.bin must exist for LUNCUSDT"
    _, vals = read_bin(luncusdt_close)

    # None of the values should equal the Luna-2.0 sentinel price * 1.01.
    luna2_close = _LUNA2_BASE_PRICE * 1.01
    for i, v in enumerate(vals):
        if not math.isnan(v):
            assert abs(v - luna2_close) > 1.0, (
                f"close[{i}]={v} looks like a Luna-2.0 price ({luna2_close}); the script fetched beyond the cap!"
            )


def test_acquire_old_luna_gap_is_nan(tmp_path: Path) -> None:
    """Gap days between old-LUNA cap+1 and LUNC first-1 must be NaN (qlib suspension)."""
    from cli.data.scripts.acquire_old_luna import acquire_old_luna

    paths, src = _seed_base_dataset(tmp_path)
    mirror_root = paths.backup_dir / "raw"

    acquire_old_luna(paths, src, cap=_TEST_CAP, mirror_root=mirror_root)

    # Gap: 2024-01-05 and 2024-01-06 (cap+1 .. LUNC_first-1).
    # Number of gap days = (LUNC_first - cap) - 1 = (2024-01-07 - 2024-01-04) - 1 = 2.
    n_gap = (_LUNC_FROM - _TEST_CAP).days - 1
    gap_days = [_TEST_CAP + dt.timedelta(days=i + 1) for i in range(n_gap)]
    assert gap_days == [dt.date(2024, 1, 5), dt.date(2024, 1, 6)], f"unexpected gap_days: {gap_days}"

    luncusdt_close = paths.data_dir / "features" / "luncusdt" / "close.day.bin"
    _, close_vals = read_bin(luncusdt_close)

    idx = load_index(paths.data_dir)
    assert idx is not None
    lunc_entry = idx.pairs["LUNCUSDT"].intervals["1d"]
    lunc_from = dt.date.fromisoformat(lunc_entry.from_date)

    # Build calendar positions for the gap days.
    cal_from = dt.date.fromisoformat(idx.calendar.from_date)
    _, all_vals = read_bin(luncusdt_close)

    # Compute the index of each gap day relative to the LUNCUSDT bin start.
    start_header, all_vals = read_bin(luncusdt_close)
    # start_header is the float32 calendar start index of the LUNCUSDT bin.
    lunc_cal_offset = int(start_header)
    lunc_from_cal_idx = (lunc_from - cal_from).days
    # Each value index in the bin maps to (lunc_cal_offset + bin_pos) global calendar day.
    for gap_day in gap_days:
        gap_cal_idx = (gap_day - cal_from).days
        bin_pos = gap_cal_idx - lunc_cal_offset
        assert 0 <= bin_pos < len(all_vals), f"gap day {gap_day} out of bin range"
        assert math.isnan(float(all_vals[bin_pos])), (
            f"close on gap day {gap_day} (bin_pos={bin_pos}) should be NaN, got {all_vals[bin_pos]}"
        )


def test_acquire_old_luna_idempotent(tmp_path: Path) -> None:
    """Second call returns 'already-acquired' status; index is byte-identical."""
    from cli.data.scripts.acquire_old_luna import acquire_old_luna

    paths, src = _seed_base_dataset(tmp_path)
    mirror_root = paths.backup_dir / "raw"

    # Run 1.
    acquire_old_luna(paths, src, cap=_TEST_CAP, mirror_root=mirror_root)
    index_bytes_run1 = (paths.data_dir / "index.json").read_bytes()

    # Run 2.
    result2 = acquire_old_luna(paths, src, cap=_TEST_CAP, mirror_root=mirror_root)

    assert result2.get("status") == "already-acquired", f"expected status='already-acquired' on re-run, got {result2}"

    # index.json must be byte-identical.
    index_bytes_run2 = (paths.data_dir / "index.json").read_bytes()
    assert index_bytes_run1 == index_bytes_run2, "index.json changed on re-run (not idempotent)"


def test_acquire_old_luna_dataset_passes_verify(tmp_path: Path) -> None:
    """verify_dataset must pass cleanly after acquisition."""
    from cli.data.scripts.acquire_old_luna import acquire_old_luna

    paths, src = _seed_base_dataset(tmp_path)
    mirror_root = paths.backup_dir / "raw"

    acquire_old_luna(paths, src, cap=_TEST_CAP, mirror_root=mirror_root)

    report = verify_dataset(paths.data_dir)
    assert report.ok, f"verify_dataset failed after acquisition: {report.problems}"


def test_acquire_old_luna_raises_on_missing_dataset(tmp_path: Path) -> None:
    """Raises RuntimeError when no index.json exists (no dataset built yet)."""
    from cli.data.scripts.acquire_old_luna import acquire_old_luna

    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = FakeSource()
    src.add_pair("LUNAUSDT", "LUNA", "USDT")
    src.add_pair("LUNCUSDT", "LUNC", "USDT")

    with pytest.raises(RuntimeError, match=r"no index\.json"):
        acquire_old_luna(paths, src, cap=_TEST_CAP, mirror_root=tmp_path / "raw")


def test_acquire_old_luna_phase1_already_done_resumes_phase2(tmp_path: Path) -> None:
    """If LUNAUSDT is already in the index (Phase 1 done, Phase 2 pending), skip Phase 1."""
    from cli.data.scripts.acquire_old_luna import acquire_old_luna

    paths, src = _seed_base_dataset(tmp_path)
    mirror_root = paths.backup_dir / "raw"

    # Simulate: a previous run completed Phase 1 (LUNAUSDT is in index) but crashed
    # before Phase 2. We reproduce this by running the full acquire once, then manually
    # re-inserting LUNAUSDT into a fresh dataset seeded without the prior run's
    # Phase 2 rename — it's easier to just test that a clean first run works
    # and that a re-run after success returns already-acquired (the idempotency test covers this).
    # What we test here: if LUNAUSDT IS in the index, the function proceeds to rename.
    # We do this by seeding a dataset that includes LUNAUSDT but not LUNCUSDT.
    pairs2 = tmp_path / "pairs2.txt"
    pairs2.write_text("BTCUSDT\n")
    paths2 = DatasetPaths(data_dir=tmp_path / "data2", backup_dir=tmp_path / "bk2")

    src2 = FakeSource()
    src2.add_pair("BTCUSDT", "BTC", "USDT")
    src2.add_pair("LUNAUSDT", "LUNA", "USDT")
    src2.add_pair("LUNCUSDT", "LUNC", "USDT")

    cur = _BTC_FROM
    while cur <= _BTC_TO:
        src2.add_kline("BTCUSDT", "1d", cur)
        cur += dt.timedelta(days=1)

    # Old LUNA data for the initial pairs2 download.
    cur = _LUNA_OLD_FROM
    while cur <= _LUNA_OLD_TO:
        src2.add_kline("LUNAUSDT", "1d", cur, base_price=100.0)
        cur += dt.timedelta(days=1)

    # LUNC tail.
    cur = _LUNC_FROM
    while cur <= _LUNC_TO:
        src2.add_kline("LUNCUSDT", "1d", cur, base_price=_LUNC_BASE_PRICE)
        cur += dt.timedelta(days=1)

    # Build dataset with both BTCUSDT and LUNAUSDT (cap already applied).
    pairs2_file = tmp_path / "pairs2_both.txt"
    pairs2_file.write_text("BTCUSDT\nLUNAUSDT\n")
    download_pipeline(paths2, pairs2_file, "1d", _BTC_FROM, _BTC_TO, src2)

    # Truncate LUNAUSDT in FakeSource to simulate cap: remove post-cap klines.
    # (FakeSource doesn't support deletion, but our dataset already has only cap-bounded data.)

    idx = load_index(paths2.data_dir)
    assert idx is not None
    assert "LUNAUSDT" in idx.pairs
    assert "LUNCUSDT" not in idx.pairs

    # Now call acquire_old_luna — should skip Phase 1 (LUNAUSDT present) and run Phase 2.
    result = acquire_old_luna(paths2, src2, cap=_TEST_CAP, mirror_root=paths2.backup_dir / "raw")

    idx_after = load_index(paths2.data_dir)
    assert idx_after is not None
    assert "LUNCUSDT" in idx_after.pairs, "LUNCUSDT must be present after Phase 2"
    assert "LUNAUSDT" not in idx_after.pairs, "LUNAUSDT must be gone after rename"
    assert verify_dataset(paths2.data_dir).ok


def test_main_resolves_paths_and_calls_core(tmp_path: Path, monkeypatch) -> None:
    """main() must not crash when config + core are provided; verifies config API."""
    import sys

    from cli.config import AppConfig, FetchConfig
    from cli.data.scripts.acquire_old_luna import main

    called_with = {}

    def fake_load_config(config_path=None):
        return AppConfig(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk", fetch=FetchConfig())

    def fake_acquire(paths, source, *, cap, mirror_root=None, dry_run=False):
        called_with["paths"] = paths
        called_with["source"] = source
        called_with["cap"] = cap
        return {"status": "done"}

    monkeypatch.setattr("cli.data.scripts.acquire_old_luna.load_config", fake_load_config)
    monkeypatch.setattr("cli.data.scripts.acquire_old_luna.acquire_old_luna", fake_acquire)
    monkeypatch.setattr(sys, "argv", ["acquire_old_luna"])

    main()  # must not raise

    assert "paths" in called_with
    assert called_with["paths"].data_dir == tmp_path / "data"
    assert called_with["paths"].backup_dir == tmp_path / "bk"
    assert called_with["cap"] is not None
