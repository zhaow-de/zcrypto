"""Tests for delist_pipeline and _delist_plan."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from cli.data.index import load_index
from cli.data.layout import DatasetPaths
from cli.data.pipeline import PipelineError, delist_pipeline, download_pipeline
from cli.data.qlib_writer import read_bin
from cli.data.verify import verify_dataset
from tests.data_fixtures import FakeSource

# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_three_pairs_uniform(tmp_path: Path) -> DatasetPaths:
    """BTC + ETH + SOL all on 2024-01-01..2024-01-05."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\nSOLUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    src.add_pair("ETHUSDT", "ETH", "USDT")
    src.add_pair("SOLUSDT", "SOL", "USDT")
    for i in range(5):
        d = dt.date(2024, 1, 1) + dt.timedelta(days=i)
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            src.add_kline(sym, "1d", d)
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    return paths


def _seed_ragged_left_two_pairs(tmp_path: Path) -> DatasetPaths:
    """BTC on 2024-01-01..2024-01-05 (calendar earliest), ETH on 2024-01-03..2024-01-05."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    src.add_pair("ETHUSDT", "ETH", "USDT")
    for i in range(5):
        src.add_kline("BTCUSDT", "1d", dt.date(2024, 1, 1) + dt.timedelta(days=i))
    for i in range(3):
        src.add_kline("ETHUSDT", "1d", dt.date(2024, 1, 3) + dt.timedelta(days=i))
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    return paths


def _seed_single_pair(tmp_path: Path) -> DatasetPaths:
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    for i in range(3):
        src.add_kline("BTCUSDT", "1d", dt.date(2024, 1, 1) + dt.timedelta(days=i))
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 3), src)
    return paths


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_delist_happy_no_calendar_trim(tmp_path):
    """Remove one of three uniform pairs; calendar stays identical."""
    paths = _seed_three_pairs_uniform(tmp_path)
    data_dir = paths.data_dir
    delist_pipeline(paths, "BTCUSDT")
    idx = load_index(data_dir)
    assert set(idx.pairs.keys()) == {"ETHUSDT", "SOLUSDT"}
    cal = (data_dir / "calendars" / "day.txt").read_text().strip().splitlines()
    assert cal[0] == "2024-01-01" and cal[-1] == "2024-01-05"
    assert verify_dataset(data_dir).ok


def test_delist_front_trim_rewrites_headers(tmp_path):
    """Remove BTC (covers 2024-01-01..02 uniquely); ETH's bins get headers rewritten to 0."""
    paths = _seed_ragged_left_two_pairs(tmp_path)
    data_dir = paths.data_dir
    delist_pipeline(paths, "BTCUSDT")
    # Calendar should now start at 2024-01-03 (ETH's first date)
    cal = (data_dir / "calendars" / "day.txt").read_text().strip().splitlines()
    assert cal[0] == "2024-01-03"
    assert cal[-1] == "2024-01-05"
    # ETH's bins: header (start_index) must now be 0 in the new calendar
    eth_feature_dir = data_dir / "features" / "ethusdt"
    for bin_path in sorted(eth_feature_dir.iterdir()):
        if bin_path.suffix == ".bin":
            header, _ = read_bin(bin_path)
            assert header == 0, f"{bin_path.name}: expected header=0, got {header}"
    assert verify_dataset(data_dir).ok


def test_delist_refuses_not_in_index(tmp_path):
    """Delisting a symbol not in the index raises PipelineError."""
    paths = _seed_three_pairs_uniform(tmp_path)
    with pytest.raises(PipelineError, match=r"not in index"):
        delist_pipeline(paths, "XYZUSDT")


def test_delist_refuses_last_pair(tmp_path):
    """Delisting the only pair raises PipelineError about empty dataset."""
    paths = _seed_single_pair(tmp_path)
    with pytest.raises(PipelineError, match=r"would leave|empty"):
        delist_pipeline(paths, "BTCUSDT")


def test_delist_refuses_gap_creating(tmp_path):
    """Delisting a pair that uniquely covers a date range in the middle of the calendar
    (no remaining pair covers it) → PipelineError, no mutation."""
    # Seed three pairs: A covers Jan 1-3, B covers Jan 1-7 (the bridge), C covers Jan 5-7.
    # Calendar union: Jan 1-7 (contiguous, because B covers everything).
    # Delisting B leaves A (Jan 1-3) and C (Jan 5-7) — gap on Jan 4.
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("AUSDT\nBUSDT\nCUSDT\n")
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "bk"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    src = FakeSource()
    # AUSDT is non-TRADING (delisted earlier) so download's Change C fetches only its
    # historical [Jan 1..Jan 3] range without requiring data at arg_to=Jan 7.
    src.add_pair("AUSDT", "A", "USDT", status="BREAK")
    src.add_pair("BUSDT", "B", "USDT")
    src.add_pair("CUSDT", "C", "USDT")
    for i in range(3):  # A: Jan 1-3
        src.add_kline("AUSDT", "1d", dt.date(2024, 1, 1) + dt.timedelta(days=i))
    for i in range(7):  # B: Jan 1-7
        src.add_kline("BUSDT", "1d", dt.date(2024, 1, 1) + dt.timedelta(days=i))
    for i in range(3):  # C: Jan 5-7
        src.add_kline("CUSDT", "1d", dt.date(2024, 1, 5) + dt.timedelta(days=i))
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 7), src)

    snaps_before = sorted((backup_dir / "snapshots").glob("*.tar.gz"))
    with pytest.raises(PipelineError, match=r"non-contiguous|gap"):
        delist_pipeline(paths, "BUSDT")
    snaps_after = sorted((backup_dir / "snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after, "refusal must not take a snapshot"
    # Dataset unchanged
    idx = load_index(data_dir)
    assert "BUSDT" in idx.pairs


def test_delist_dry_run_no_mutation(tmp_path, capsys):
    """--dry-run prints the plan but leaves the dataset intact."""
    paths = _seed_three_pairs_uniform(tmp_path)
    data_dir = paths.data_dir
    backup_dir = paths.backup_dir
    snaps_before = sorted((backup_dir / "snapshots").glob("*.tar.gz"))
    delist_pipeline(paths, "BTCUSDT", dry_run=True)
    snaps_after = sorted((backup_dir / "snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after
    captured = capsys.readouterr()
    assert "BTCUSDT" in captured.out
    idx = load_index(data_dir)
    assert "BTCUSDT" in idx.pairs  # unchanged
