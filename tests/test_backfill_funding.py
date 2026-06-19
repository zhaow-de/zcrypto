"""Tests for scripts/backfill_funding.py — FakeSource only, no network.

Task 6 (iter-15): one-time idempotent $funding retrofit script.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

from cli.data.layout import DatasetPaths
from cli.data.pipeline import download_pipeline
from cli.data.qlib_writer import read_bin
from tests.data_fixtures import FakeSource

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_klines_only(tmp_path: Path) -> tuple[DatasetPaths, FakeSource]:
    """Seed a two-pair (BTC + ETH) dataset with klines but NO funding archives.

    This simulates a dataset built before the funding layer was added.
    Returns (paths, source) so tests can later add funding to the source
    and call retrofit_funding.
    """
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    src.add_pair("ETHUSDT", "ETH", "USDT")
    for i in range(3):
        d = dt.date(2024, 1, 1) + dt.timedelta(days=i)
        src.add_kline("BTCUSDT", "1d", d)
        src.add_kline("ETHUSDT", "1d", d)
    # Download WITHOUT funding archives — simulating the pre-funding dataset state.
    # FakeSource.fetch_funding_archive returns None for un-registered archives,
    # so funding.day.bin will be written with all-NaN values by the current pipeline.
    # We need to remove those bins after download to simulate the truly pre-funding state.
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 3), src)

    # Remove funding.day.bin to simulate a dataset built before funding was added.
    for sym in ("btcusdt", "ethusdt"):
        funding_bin = paths.data_dir / "features" / sym / "funding.day.bin"
        if funding_bin.exists():
            funding_bin.unlink()

    return paths, src


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_retrofit_funding_writes_bins(tmp_path: Path) -> None:
    """First run: retrofit_funding writes funding.day.bin for each instrument."""
    from scripts.backfill_funding import retrofit_funding

    paths, src = _seed_klines_only(tmp_path)

    # Pre: no funding.day.bin exists
    assert not (paths.data_dir / "features" / "btcusdt" / "funding.day.bin").exists()
    assert not (paths.data_dir / "features" / "ethusdt" / "funding.day.bin").exists()

    # Add funding archives to the source
    src.add_funding("BTCUSDT", 2024, 1)
    src.add_funding("ETHUSDT", 2024, 1)

    mirror_root = paths.backup_dir / "raw"
    summary = retrofit_funding(paths, src, mirror_root=mirror_root)

    # Post: both bins exist
    btc_bin = paths.data_dir / "features" / "btcusdt" / "funding.day.bin"
    eth_bin = paths.data_dir / "features" / "ethusdt" / "funding.day.bin"
    assert btc_bin.exists(), "BTC funding.day.bin must be written"
    assert eth_bin.exists(), "ETH funding.day.bin must be written"

    # Values: synthetic archive has 3 settlements on 2024-01-01 (0.0001+0.0002+0.0003=0.0006)
    # The pair covers 2024-01-01..2024-01-03; Jan 2 and Jan 3 have no settlements → NaN.
    _, btc_vals = read_bin(btc_bin)
    assert len(btc_vals) == 3, f"expected 3 rows, got {len(btc_vals)}"
    assert abs(float(btc_vals[0]) - 0.0006) < 1e-5, f"Jan 1 funding sum wrong: {btc_vals[0]}"
    assert math.isnan(float(btc_vals[1])), "Jan 2 should be NaN (no settlement)"
    assert math.isnan(float(btc_vals[2])), "Jan 3 should be NaN (no settlement)"

    # Summary should show both instruments written
    assert summary["written"] == 2
    assert summary["skipped"] == 0


def test_retrofit_funding_idempotent(tmp_path: Path) -> None:
    """Second run: retrofit_funding is byte-identical — nothing overwritten."""
    from scripts.backfill_funding import retrofit_funding

    paths, src = _seed_klines_only(tmp_path)
    src.add_funding("BTCUSDT", 2024, 1)
    src.add_funding("ETHUSDT", 2024, 1)

    mirror_root = paths.backup_dir / "raw"

    # Run 1
    retrofit_funding(paths, src, mirror_root=mirror_root)

    btc_bin = paths.data_dir / "features" / "btcusdt" / "funding.day.bin"
    eth_bin = paths.data_dir / "features" / "ethusdt" / "funding.day.bin"

    btc_bytes_run1 = btc_bin.read_bytes()
    eth_bytes_run1 = eth_bin.read_bytes()

    # Run 2
    summary2 = retrofit_funding(paths, src, mirror_root=mirror_root)

    # Bytes must be identical
    assert btc_bin.read_bytes() == btc_bytes_run1, "BTC funding.day.bin must be byte-identical on re-run"
    assert eth_bin.read_bytes() == eth_bytes_run1, "ETH funding.day.bin must be byte-identical on re-run"

    # Summary: 0 written, 2 skipped
    assert summary2["written"] == 0
    assert summary2["skipped"] == 2


def test_retrofit_funding_does_not_touch_ohlcv(tmp_path: Path) -> None:
    """retrofit_funding must not modify OHLCV bins."""
    from scripts.backfill_funding import retrofit_funding

    paths, src = _seed_klines_only(tmp_path)
    src.add_funding("BTCUSDT", 2024, 1)
    src.add_funding("ETHUSDT", 2024, 1)

    # Capture OHLCV bin bytes before retrofit
    ohlcv_snapshots: dict[str, bytes] = {}
    for sym in ("btcusdt", "ethusdt"):
        for field in ("open", "close", "high", "low", "volume"):
            p = paths.data_dir / "features" / sym / f"{field}.day.bin"
            if p.exists():
                ohlcv_snapshots[str(p)] = p.read_bytes()

    mirror_root = paths.backup_dir / "raw"
    retrofit_funding(paths, src, mirror_root=mirror_root)

    # Verify OHLCV bins unchanged
    for path_str, before_bytes in ohlcv_snapshots.items():
        after_bytes = Path(path_str).read_bytes()
        assert after_bytes == before_bytes, f"{path_str} was modified by retrofit_funding"


def test_retrofit_funding_dataset_passes_verify(tmp_path: Path) -> None:
    """After retrofit, verify_dataset must pass — funding.day.bin must be indexed, not orphaned."""
    from cli.data.verify import verify_dataset
    from scripts.backfill_funding import retrofit_funding

    paths, src = _seed_klines_only(tmp_path)
    src.add_funding("BTCUSDT", 2024, 1)
    src.add_funding("ETHUSDT", 2024, 1)

    mirror_root = paths.backup_dir / "raw"
    retrofit_funding(paths, src, mirror_root=mirror_root)

    report = verify_dataset(paths.data_dir)
    assert report.ok, f"verify_dataset failed after retrofit: {report.problems}"
