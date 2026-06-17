"""Validate the README/spec documented forward-migration path.

A pre-relayout combined dir (everything in one root) can be migrated to the
two-root layout (data_dir + backup_dir) by the `mv` sequence documented in
the spec, and the resulting dataset passes verify + stays functional.
"""

import datetime as dt
import shutil

from cli.data.layout import DatasetPaths
from cli.data.pipeline import backfill_pipeline, download_pipeline
from cli.data.verify import verify_dataset
from tests.data_fixtures import FakeSource

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INTERVAL = "1d"
_FROM = dt.date(2024, 1, 1)
_TO = dt.date(2024, 1, 5)  # 5 days: 01-01..01-05


def _make_fake_source() -> FakeSource:
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    src.add_pair("ETHUSDT", "ETH", "USDT")
    for i in range(7):  # extra days so backfill can extend
        d = _FROM + dt.timedelta(days=i)
        src.add_kline("BTCUSDT", _INTERVAL, d)
        src.add_kline("ETHUSDT", _INTERVAL, d)
    return src


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_migration_yields_verify_clean_and_functional_layout(tmp_path):
    """The documented forward-migration `mv` sequence produces a verify-clean two-root layout
    that a subsequent backfill operation accepts without error."""

    # --- Step 1: seed a canonical two-root dataset via download_pipeline ---
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backup"
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    pairs_file = tmp_path / "pairs.txt"
    pairs_file.write_text("BTCUSDT\nETHUSDT\n")
    src = _make_fake_source()

    download_pipeline(paths, pairs_file, _INTERVAL, _FROM, _TO, src)
    assert verify_dataset(data_dir, fail_on_gap=True).ok, "seed dataset must be verify-clean"

    # --- Step 2: simulate the OLD pre-relayout combined dir ---
    # Legacy layout had everything under one root: compiled dirs at the top
    # and backup dirs as dot-prefixed siblings.
    combined = tmp_path / "combined"
    combined.mkdir()

    # Copy compiled contents (calendars, instruments, features, index.json) into combined/
    for name in ("calendars", "instruments", "features"):
        shutil.copytree(data_dir / name, combined / name)
    shutil.copy2(data_dir / "index.json", combined / "index.json")

    # Recreate legacy dot-prefixed backup dirs: raw/ → .raw/, snapshots/ → .snapshots/
    shutil.copytree(backup_dir / "raw", combined / ".raw")
    shutil.copytree(backup_dir / "snapshots", combined / ".snapshots")

    # Sanity: combined/ now looks like the old combined dir
    assert (combined / "index.json").exists()
    assert (combined / ".raw").is_dir()
    assert (combined / ".snapshots").is_dir()

    # --- Step 3: apply the documented forward migration ---
    # Move compiled dirs out of combined/ into a fresh migrated_data/
    migrated_data = tmp_path / "migrated_data"
    migrated_data.mkdir()
    for name in ("calendars", "instruments", "features", "index.json"):
        shutil.move(str(combined / name), str(migrated_data / name))

    # Rename dot-prefixed backup dirs back to plain names (combined/ becomes backup_dir)
    (combined / ".raw").rename(combined / "raw")
    (combined / ".snapshots").rename(combined / "snapshots")

    # --- Step 4: verify the migrated data_dir is clean ---
    report = verify_dataset(migrated_data, fail_on_gap=True)
    assert report.ok is True, report.problems

    # --- Step 5: a subsequent pipeline operation on the migrated layout works ---
    migrated_paths = DatasetPaths(data_dir=migrated_data, backup_dir=combined)
    extend_to = _TO + dt.timedelta(days=2)  # 2026-01-07
    backfill_pipeline(migrated_paths, _INTERVAL, extend_to, src)

    assert verify_dataset(migrated_data, fail_on_gap=True).ok is True
