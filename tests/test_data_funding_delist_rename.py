"""Explicit funding-specific tests for delist_pipeline and rename_pipeline.

Task 4 (iter-15): these tests lock the behavior that was added in Task 3 —
delist removes funding.day.bin along with OHLCV bins, and rename carries
funding.day.bin across old→new with the rename gap left as NaN.
No production changes expected; any FAIL indicates a real gap.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

from cli.data.index import load_index
from cli.data.layout import DatasetPaths
from cli.data.pipeline import delist_pipeline, download_pipeline, rename_pipeline
from cli.data.qlib_writer import read_bin
from cli.data.verify import verify_dataset
from tests.data_fixtures import FakeSource

# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_two_pairs_with_funding(tmp_path: Path) -> DatasetPaths:
    """BTC + ETH on 2024-01-01..2024-01-05; funding registered for both.

    BTC has funding for Jan 2024; ETH has funding for Jan 2024 as well.
    Returns paths after download_pipeline has committed the dataset.
    """
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    src.add_pair("ETHUSDT", "ETH", "USDT")
    for i in range(5):
        d = dt.date(2024, 1, 1) + dt.timedelta(days=i)
        src.add_kline("BTCUSDT", "1d", d)
        src.add_kline("ETHUSDT", "1d", d)
    # Register funding archives: the fixture produces 3 rows for day-1 of the month
    src.add_funding("BTCUSDT", 2024, 1)
    src.add_funding("ETHUSDT", 2024, 1)
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    return paths


def _seed_old_pair_with_funding(tmp_path: Path, old_sym: str, base: str, last_day: dt.date) -> tuple[DatasetPaths, FakeSource]:
    """Single pair OLD on 2024-01-01..last_day with funding for Jan 2024."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text(f"{old_sym}\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = FakeSource()
    src.add_pair(old_sym, base, "USDT", status="BREAK")
    n = (last_day - dt.date(2024, 1, 1)).days + 1
    for i in range(n):
        src.add_kline(old_sym, "1d", dt.date(2024, 1, 1) + dt.timedelta(days=i))
    src.add_funding(old_sym, 2024, 1)
    download_pipeline(paths, pairs, "1d", dt.date(2024, 1, 1), last_day, src)
    return paths, src


# ---------------------------------------------------------------------------
# Delist tests
# ---------------------------------------------------------------------------


def test_delist_removes_funding_bin(tmp_path):
    """delist_pipeline must remove funding.day.bin for the delisted pair.

    After delisting BTCUSDT the entire features/btcusdt/ dir is gone,
    including funding.day.bin. The remaining ETH pair still has its
    funding.day.bin intact and the dataset passes verify.
    """
    paths = _seed_two_pairs_with_funding(tmp_path)
    data_dir = paths.data_dir

    # Pre: both pairs have funding.day.bin
    assert (data_dir / "features" / "btcusdt" / "funding.day.bin").exists()
    assert (data_dir / "features" / "ethusdt" / "funding.day.bin").exists()

    delist_pipeline(paths, "BTCUSDT")

    # Post: BTC dir is gone (funding + OHLCV all removed)
    assert not (data_dir / "features" / "btcusdt").exists()

    # ETH funding.day.bin still present
    eth_funding = data_dir / "features" / "ethusdt" / "funding.day.bin"
    assert eth_funding.exists(), "remaining pair's funding.day.bin must survive delist"

    # ETH funding bin is readable and has the right length
    _, funding_vals = read_bin(eth_funding)
    assert len(funding_vals) == 5, "ETH funding bin should have 5 rows (Jan 1-5)"

    # Dataset is still valid
    assert verify_dataset(data_dir).ok

    # BTC no longer in index
    idx = load_index(data_dir)
    assert "BTCUSDT" not in idx.pairs
    assert "ETHUSDT" in idx.pairs

    # ETH index registers funding field
    eth_fields = idx.pairs["ETHUSDT"].intervals["1d"].fields
    assert "funding" in eth_fields, "funding must remain registered in ETH's index entry"


# ---------------------------------------------------------------------------
# Rename (Variant 1) tests
# ---------------------------------------------------------------------------


def test_rename_v1_carries_funding_bin(tmp_path):
    """rename_pipeline (Variant 1, no gap) copies funding.day.bin from OLD to NEW.

    OLD ends 2024-01-05, NEW starts 2024-01-06 → no synthetic gap.
    After rename, features/newusdt/funding.day.bin should exist with the
    same row count as the OHLCV bins, and OLD's funding dir is gone.
    """
    paths, src = _seed_old_pair_with_funding(tmp_path, "OLDUSDT", "OLD", dt.date(2024, 1, 5))
    data_dir = paths.data_dir

    # Add NEW pair with data starting immediately after OLD ends (no gap)
    src.add_pair("NEWUSDT", "NEW", "USDT")
    src.add_kline("NEWUSDT", "1d", dt.date(2024, 1, 6))
    src.add_kline("NEWUSDT", "1d", dt.date(2024, 1, 7))
    # No funding registered for NEWUSDT — source returns None for fetch_funding_archive

    rename_pipeline(paths, "OLDUSDT", "NEWUSDT", src)

    # OLD dir gone
    assert not (data_dir / "features" / "oldusdt").exists()

    # NEW has funding.day.bin
    new_funding = data_dir / "features" / "newusdt" / "funding.day.bin"
    assert new_funding.exists(), "rename must carry funding.day.bin from OLD to NEW"

    # Row count: OLD's 5 days (Jan 1-5), no gap fill
    _, funding_vals = read_bin(new_funding)
    assert len(funding_vals) == 5, f"expected 5 funding rows (OLD's span), got {len(funding_vals)}"

    # All 5 rows should be non-NaN (funding was seeded for Jan 2024)
    # FakeSource.add_funding produces 3 settlements on day-1; days 2-5 have no
    # settlements → NaN is acceptable for those, but day-1 should be non-NaN.
    assert not math.isnan(funding_vals[0]), "first day funding should be the seeded value"

    # Verify + index check
    assert verify_dataset(data_dir).ok
    idx = load_index(data_dir)
    new_fields = idx.pairs["NEWUSDT"].intervals["1d"].fields
    assert "funding" in new_fields, "funding must be registered in NEW's index entry after rename"


def test_rename_v1_gap_funding_is_nan(tmp_path):
    """rename_pipeline (Variant 1, 2-day gap) fills funding gap days with NaN.

    OLD ends 2024-01-05, NEW starts 2024-01-08 → 2 synthetic gap days (Jan 6-7).
    The funding.day.bin for NEW should have:
      - 5 rows of OLD-era funding (indices 0-4)
      - 2 NaN rows for the gap (indices 5-6)
    (NEW's own days aren't present in Variant 1's bin — it stops at new_to = Jan 7.)
    """
    paths, src = _seed_old_pair_with_funding(tmp_path, "OLDUSDT", "OLD", dt.date(2024, 1, 5))
    data_dir = paths.data_dir

    # Add NEW pair with 2-day gap: data starts 2024-01-08 (gap on Jan 6-7)
    src.add_pair("NEWUSDT", "NEW", "USDT")
    src.add_kline("NEWUSDT", "1d", dt.date(2024, 1, 8))
    src.add_kline("NEWUSDT", "1d", dt.date(2024, 1, 9))

    rename_pipeline(paths, "OLDUSDT", "NEWUSDT", src)

    new_funding = data_dir / "features" / "newusdt" / "funding.day.bin"
    assert new_funding.exists(), "rename must produce funding.day.bin for NEW"

    _, funding_vals = read_bin(new_funding)
    # Variant 1 stops at new_to = new_first - 1 = Jan 7;
    # so bin has OLD's 5 rows + 2 gap rows = 7 total.
    assert len(funding_vals) == 7, f"expected 7 rows (5 OLD + 2 gap), got {len(funding_vals)}"

    # The 2 gap days (indices 5 and 6) must be NaN
    assert math.isnan(funding_vals[5]), "gap day 1 funding must be NaN (rename gap)"
    assert math.isnan(funding_vals[6]), "gap day 2 funding must be NaN (rename gap)"

    assert verify_dataset(data_dir).ok
    idx = load_index(data_dir)
    assert "funding" in idx.pairs["NEWUSDT"].intervals["1d"].fields


# ---------------------------------------------------------------------------
# Rename (Variant 2) tests
# ---------------------------------------------------------------------------


def _seed_two_pairs_for_merge_with_funding(
    tmp_path: Path,
    old_range: tuple[dt.date, dt.date],
    new_range: tuple[dt.date, dt.date],
) -> tuple[DatasetPaths, FakeSource]:
    """Seed OLD (BREAK) + NEW (TRADING), both with funding, via download_pipeline."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("OLDUSDT\nNEWUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = FakeSource()
    src.add_pair("OLDUSDT", "OLD", "USDT", status="BREAK")
    src.add_pair("NEWUSDT", "NEW", "USDT")

    cur = old_range[0]
    while cur <= old_range[1]:
        src.add_kline("OLDUSDT", "1d", cur)
        cur += dt.timedelta(days=1)

    cur = new_range[0]
    while cur <= new_range[1]:
        src.add_kline("NEWUSDT", "1d", cur)
        cur += dt.timedelta(days=1)

    # Register funding for each month spanned
    for d in (old_range[0], old_range[1], new_range[0], new_range[1]):
        src.add_funding("OLDUSDT", d.year, d.month)
        src.add_funding("NEWUSDT", d.year, d.month)

    download_pipeline(paths, pairs, "1d", old_range[0], new_range[1], src)
    return paths, src


def test_rename_v2_merge_carries_funding_and_gap_nan(tmp_path):
    """rename_pipeline (Variant 2, 2-day gap) merges funding bins: OLD + NaN gap + NEW.

    OLD ends Jan 10, NEW starts Jan 13 → 2 synthetic gap days (Jan 11-12).
    Merged funding.day.bin:
      - 10 rows from OLD (Jan 1-10)
      - 2 NaN rows for the gap (Jan 11-12)
      - 3 rows from NEW (Jan 13-15)
      = 15 rows total
    Gap rows at indices 10 and 11 must be NaN.
    """
    paths, src = _seed_two_pairs_for_merge_with_funding(
        tmp_path,
        old_range=(dt.date(2024, 1, 1), dt.date(2024, 1, 10)),
        new_range=(dt.date(2024, 1, 13), dt.date(2024, 1, 15)),
    )
    data_dir = paths.data_dir

    rename_pipeline(paths, "OLDUSDT", "NEWUSDT", src)

    # OLD dir gone
    assert not (data_dir / "features" / "oldusdt").exists()

    # NEW funding.day.bin exists
    new_funding = data_dir / "features" / "newusdt" / "funding.day.bin"
    assert new_funding.exists(), "rename must produce merged funding.day.bin for NEW"

    _, funding_vals = read_bin(new_funding)
    # 10 OLD + 2 gap + 3 NEW = 15 rows
    assert len(funding_vals) == 15, f"expected 15 rows (10 OLD + 2 gap + 3 NEW), got {len(funding_vals)}"

    # Gap days at indices 10 and 11 must be NaN
    assert math.isnan(funding_vals[10]), "gap day 1 (Jan 11) funding must be NaN"
    assert math.isnan(funding_vals[11]), "gap day 2 (Jan 12) funding must be NaN"

    # Verify dataset integrity
    assert verify_dataset(data_dir).ok

    # Index: OLDUSDT gone, NEWUSDT has funding registered
    idx = load_index(data_dir)
    assert "OLDUSDT" not in idx.pairs
    new_fields = idx.pairs["NEWUSDT"].intervals["1d"].fields
    assert "funding" in new_fields, "funding must be registered in NEW's merged index entry"


def test_rename_v2_merge_no_gap_carries_funding(tmp_path):
    """rename_pipeline (Variant 2, no gap) merges funding bins contiguously.

    OLD ends Jan 10, NEW starts Jan 11 → no gap.
    Merged funding.day.bin has 10 + 5 = 15 rows, all non-NaN where seeded.
    """
    paths, src = _seed_two_pairs_for_merge_with_funding(
        tmp_path,
        old_range=(dt.date(2024, 1, 1), dt.date(2024, 1, 10)),
        new_range=(dt.date(2024, 1, 11), dt.date(2024, 1, 15)),
    )
    data_dir = paths.data_dir

    rename_pipeline(paths, "OLDUSDT", "NEWUSDT", src)

    new_funding = data_dir / "features" / "newusdt" / "funding.day.bin"
    assert new_funding.exists()

    _, funding_vals = read_bin(new_funding)
    assert len(funding_vals) == 15, f"expected 15 rows (10 OLD + 5 NEW, no gap), got {len(funding_vals)}"

    # No NaN from a gap (all values from seeded funding or NaN due to no settlement on that day)
    # The key property: no synthetic NaN injected at the seam (index 10 = Jan 11)
    # Jan 11 is day-11, which has no funding settlement in the fixture (only day-1 is seeded) → NaN is expected
    # but NOT from synthetic gap-fill — it's a legitimate missing-settlement NaN.
    # We verify structural integrity only (verify_dataset) rather than the exact NaN pattern here.
    assert verify_dataset(data_dir).ok

    idx = load_index(data_dir)
    assert "OLDUSDT" not in idx.pairs
    assert "funding" in idx.pairs["NEWUSDT"].intervals["1d"].fields
