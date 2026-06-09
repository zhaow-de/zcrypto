import tarfile
import time

from cli.data.snapshots import SNAPSHOT_ITEMS, create_snapshot, prune_snapshots


def _populate(out_dir):
    (out_dir / "calendars").mkdir()
    (out_dir / "calendars" / "day.txt").write_text("2024-01-01\n")
    (out_dir / "instruments").mkdir()
    (out_dir / "instruments" / "all.txt").write_text("BTCUSDT\t2024-01-01\t2024-01-01\n")
    (out_dir / "features").mkdir()
    (out_dir / "features" / "btcusdt").mkdir()
    (out_dir / "features" / "btcusdt" / "close.day.bin").write_bytes(b"\x00" * 8)
    (out_dir / "index.json").write_text("{}\n")
    # noise that must be excluded
    (out_dir / ".staging").mkdir()
    (out_dir / ".staging" / "junk").write_text("ignored")


def test_create_snapshot_archives_only_documented_items(tmp_path):
    _populate(tmp_path)
    archive = create_snapshot(tmp_path, "download")
    assert archive.parent == tmp_path / ".snapshots"
    assert archive.name.endswith("-download.tar.gz")
    with tarfile.open(archive, "r:gz") as tar:
        names = sorted(tar.getnames())
    # Top-level archive entries must be exactly SNAPSHOT_ITEMS
    top_level = sorted({n.split("/", 1)[0] for n in names})
    assert top_level == sorted(SNAPSHOT_ITEMS)
    # Excluded
    assert all(".staging" not in n and ".snapshots" not in n for n in names)


def test_prune_snapshots_keeps_newest_seven(tmp_path):
    snaps = tmp_path / ".snapshots"
    snaps.mkdir()
    # Names sort chronologically because the stamps do.
    for i in range(10):
        (snaps / f"2024010{i % 10}T0000{i:02d}Z-download.tar.gz").write_bytes(b"x")
    removed = prune_snapshots(tmp_path, keep=7)
    remaining = sorted(p.name for p in snaps.iterdir())
    assert len(remaining) == 7
    assert len(removed) == 3


def test_prune_snapshots_noop_under_keep(tmp_path):
    snaps = tmp_path / ".snapshots"
    snaps.mkdir()
    (snaps / "20240101T000000Z-download.tar.gz").write_bytes(b"x")
    assert prune_snapshots(tmp_path, keep=7) == []


def test_create_snapshot_stamps_are_monotone(tmp_path):
    _populate(tmp_path)
    a = create_snapshot(tmp_path, "download")
    time.sleep(1.1)  # ensure stamp difference (UTC seconds resolution)
    b = create_snapshot(tmp_path, "download")
    assert a.name < b.name
