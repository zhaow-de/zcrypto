from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import pytest

from cli.data.index import load_index
from cli.data.layout import DatasetPaths
from cli.data.pipeline import PipelineError, download_pipeline, rename_pipeline
from cli.data.qlib_writer import read_bin
from cli.data.verify import verify_dataset
from tests.data_fixtures import FakeSource


def _seed_single_pair(tmp_path, symbol, base, quote, last_day, status="BREAK"):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text(f"{symbol}\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = FakeSource()
    src.add_pair(symbol, base, quote, status=status)
    n = (last_day - dt.date(2024, 1, 1)).days + 1
    for i in range(n):
        src.add_kline(symbol, "1d", dt.date(2024, 1, 1) + dt.timedelta(days=i))
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), last_day, src)
    return paths


def test_rename_v1_no_gap(tmp_path):
    """OLD ends 2024-09-10, NEW starts 2024-09-11 → no synthetic fill."""
    paths = _seed_single_pair(tmp_path, "MATICUSDT", "MATIC", "USDT", dt.date(2024, 9, 10), status="BREAK")
    data_dir = paths.data_dir
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")
    for d in (dt.date(2024, 9, 11), dt.date(2024, 9, 12)):
        src.add_kline("POLUSDT", "1d", d)

    rename_pipeline(paths, "MATICUSDT", "POLUSDT", src)
    idx = load_index(data_dir)
    assert "MATICUSDT" not in idx.pairs
    assert "POLUSDT" in idx.pairs
    pol = idx.pairs["POLUSDT"].intervals["1d"]
    assert pol.dates_to == "2024-09-10"  # no extension; rename only re-labels
    assert (data_dir / "features" / "polusdt").is_dir()
    assert not (data_dir / "features" / "maticusdt").exists()
    assert verify_dataset(data_dir).ok


def test_rename_v1_with_gap_fills_nan_price_zero_volume(tmp_path):
    """OLD ends 2024-09-10, NEW first archive = 2024-09-13 → 2 synthetic days.

    Gap price fields are NaN (qlib's suspension marker), volume/amount/trades are
    0.0, factor is 1.0."""
    paths = _seed_single_pair(tmp_path, "MATICUSDT", "MATIC", "USDT", dt.date(2024, 9, 10), status="BREAK")
    data_dir = paths.data_dir
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")
    for i in range(3):
        src.add_kline("POLUSDT", "1d", dt.date(2024, 9, 13) + dt.timedelta(days=i))

    rename_pipeline(paths, "MATICUSDT", "POLUSDT", src)

    # Price fields (OHLC + VWAP) on the 2 gap days are NaN.
    for field in ("open", "high", "low", "close", "vwap"):
        _, vals = read_bin(data_dir / "features" / "polusdt" / f"{field}.day.bin")
        assert math.isnan(vals[-2]), f"{field}[-2] should be NaN"
        assert math.isnan(vals[-1]), f"{field}[-1] should be NaN"
    _, vols = read_bin(data_dir / "features" / "polusdt" / "volume.day.bin")
    assert vols[-2] == pytest.approx(0.0)
    assert vols[-1] == pytest.approx(0.0)
    _, factors = read_bin(data_dir / "features" / "polusdt" / "factor.day.bin")
    assert factors[-2] == pytest.approx(1.0)
    assert factors[-1] == pytest.approx(1.0)

    idx = load_index(data_dir)
    pol = idx.pairs["POLUSDT"].intervals["1d"]
    assert pol.dates_to == "2024-09-12"  # day before NEW's first archive
    assert verify_dataset(data_dir).ok


def test_rename_v1_refuses_old_not_in_index(tmp_path):
    paths = _seed_single_pair(tmp_path, "BTCUSDT", "BTC", "USDT", dt.date(2024, 1, 5), status="TRADING")
    src = FakeSource()
    src.add_pair("XYZUSDT", "XYZ", "USDT")
    with pytest.raises(PipelineError, match=r"not in index"):
        rename_pipeline(paths, "MATICUSDT", "XYZUSDT", src)


def test_rename_v1_refuses_old_equals_new(tmp_path):
    paths = _seed_single_pair(tmp_path, "MATICUSDT", "MATIC", "USDT", dt.date(2024, 9, 10), status="BREAK")
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    with pytest.raises(PipelineError, match=r"equals|no change"):
        rename_pipeline(paths, "MATICUSDT", "MATICUSDT", src)


def test_rename_v1_refuses_new_not_in_exchange_info(tmp_path):
    paths = _seed_single_pair(tmp_path, "MATICUSDT", "MATIC", "USDT", dt.date(2024, 9, 10), status="BREAK")
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    # POLUSDT not added
    with pytest.raises(PipelineError, match=r"not found on Binance"):
        rename_pipeline(paths, "MATICUSDT", "POLUSDT", src)


def test_rename_v1_refuses_new_no_archive_yet(tmp_path):
    """NEW is in exchangeInfo but no archive days yet."""
    paths = _seed_single_pair(tmp_path, "MATICUSDT", "MATIC", "USDT", dt.date(2024, 9, 10), status="BREAK")
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")  # no add_kline calls
    with pytest.raises(PipelineError, match=r"no daily archive available"):
        rename_pipeline(paths, "MATICUSDT", "POLUSDT", src)


def test_rename_v1_dry_run_no_mutation(tmp_path, capsys):
    paths = _seed_single_pair(tmp_path, "MATICUSDT", "MATIC", "USDT", dt.date(2024, 9, 10), status="BREAK")
    data_dir = paths.data_dir
    backup_dir = paths.backup_dir
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")
    for i in range(3):
        src.add_kline("POLUSDT", "1d", dt.date(2024, 9, 13) + dt.timedelta(days=i))

    snaps_before = sorted((backup_dir / "snapshots").glob("*.tar.gz"))
    rename_pipeline(paths, "MATICUSDT", "POLUSDT", src, dry_run=True)
    snaps_after = sorted((backup_dir / "snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after
    captured = capsys.readouterr()
    assert "MATICUSDT" in captured.out and "POLUSDT" in captured.out
    # Mutation didn't happen
    assert (data_dir / "features" / "maticusdt").is_dir()


# ---------------------------------------------------------------------------
# Variant 2 tests
# ---------------------------------------------------------------------------


def _seed_two_pairs_for_merge(tmp_path, old_range, new_range):
    """Seed dataset with two pairs: OLD on old_range (BREAK status), NEW on new_range (TRADING)."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("MATICUSDT\nPOLUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")
    cur = old_range[0]
    while cur <= old_range[1]:
        src.add_kline("MATICUSDT", "1d", cur)
        cur += dt.timedelta(days=1)
    cur = new_range[0]
    while cur <= new_range[1]:
        src.add_kline("POLUSDT", "1d", cur)
        cur += dt.timedelta(days=1)
    download_pipeline(paths, pairs, "1d", old_range[0], new_range[1], src)
    return paths


def test_rename_v2_merge_no_gap(tmp_path):
    """OLD ends 2024-09-10, NEW starts 2024-09-11 → no gap, simple merge."""
    paths = _seed_two_pairs_for_merge(
        tmp_path,
        old_range=(dt.date(2024, 8, 1), dt.date(2024, 9, 10)),
        new_range=(dt.date(2024, 9, 11), dt.date(2024, 9, 20)),
    )
    data_dir = paths.data_dir
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")
    rename_pipeline(paths, "MATICUSDT", "POLUSDT", src)
    idx = load_index(data_dir)
    assert "MATICUSDT" not in idx.pairs
    pol = idx.pairs["POLUSDT"].intervals["1d"]
    assert pol.dates_from == "2024-08-01"  # extends back through OLD
    assert pol.dates_to == "2024-09-20"
    # Merged bin: OLD's 41 days + 0 gap + NEW's 10 days = 51 rows
    _, vols = read_bin(data_dir / "features" / "polusdt" / "volume.day.bin")
    assert len(vols) == 51
    assert verify_dataset(data_dir).ok


def test_rename_v2_merge_with_gap_fills(tmp_path):
    """OLD ends 2024-09-10, NEW starts 2024-09-13 → 2 synthetic days in middle."""
    paths = _seed_two_pairs_for_merge(
        tmp_path,
        old_range=(dt.date(2024, 8, 1), dt.date(2024, 9, 10)),
        new_range=(dt.date(2024, 9, 13), dt.date(2024, 9, 20)),
    )
    data_dir = paths.data_dir
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")
    rename_pipeline(paths, "MATICUSDT", "POLUSDT", src)

    idx = load_index(data_dir)
    pol = idx.pairs["POLUSDT"].intervals["1d"]
    assert pol.dates_from == "2024-08-01"
    assert pol.dates_to == "2024-09-20"
    # 41 OLD + 2 gap + 8 NEW = 51 rows
    _, vols = read_bin(data_dir / "features" / "polusdt" / "volume.day.bin")
    assert len(vols) == 51
    # Synthetic gap is at indices 41, 42: zero volume, NaN close.
    assert vols[41] == pytest.approx(0.0)
    assert vols[42] == pytest.approx(0.0)
    _, closes = read_bin(data_dir / "features" / "polusdt" / "close.day.bin")
    assert math.isnan(closes[41])
    assert math.isnan(closes[42])
    assert verify_dataset(data_dir).ok


def test_rename_v2_dry_run_no_mutation(tmp_path, capsys):
    paths = _seed_two_pairs_for_merge(
        tmp_path,
        old_range=(dt.date(2024, 8, 1), dt.date(2024, 9, 10)),
        new_range=(dt.date(2024, 9, 13), dt.date(2024, 9, 20)),
    )
    data_dir = paths.data_dir
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")
    rename_pipeline(paths, "MATICUSDT", "POLUSDT", src, dry_run=True)
    captured = capsys.readouterr()
    assert "MATICUSDT" in captured.out and "POLUSDT" in captured.out
    # Both entries unchanged
    idx = load_index(data_dir)
    assert "MATICUSDT" in idx.pairs and "POLUSDT" in idx.pairs
