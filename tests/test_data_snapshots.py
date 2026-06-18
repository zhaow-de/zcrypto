import tarfile
import time

from cli.data.snapshots import SNAPSHOT_ITEMS, create_snapshot, prune_snapshots


def _populate(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "calendars").mkdir()
    (data_dir / "calendars" / "day.txt").write_text("2024-01-01\n")
    (data_dir / "instruments").mkdir()
    (data_dir / "instruments" / "all.txt").write_text("BTCUSDT\t2024-01-01\t2024-01-01\n")
    (data_dir / "features").mkdir()
    (data_dir / "features" / "btcusdt").mkdir()
    (data_dir / "features" / "btcusdt" / "close.day.bin").write_bytes(b"\x00" * 8)
    (data_dir / "index.json").write_text("{}\n")
    # noise that must be excluded
    (data_dir / ".staging").mkdir()
    (data_dir / ".staging" / "junk").write_text("ignored")


def test_create_snapshot_archives_only_documented_items(tmp_path):
    data_dir = tmp_path / "data"
    snapshots_dir = tmp_path / "bk" / "snapshots"
    _populate(data_dir)
    archive = create_snapshot(data_dir, snapshots_dir, "download")
    assert archive.parent == snapshots_dir
    assert archive.name.endswith("-download.tar.gz")
    with tarfile.open(archive, "r:gz") as tar:
        names = sorted(tar.getnames())
    # Top-level archive entries must be exactly SNAPSHOT_ITEMS
    top_level = sorted({n.split("/", 1)[0] for n in names})
    assert top_level == sorted(SNAPSHOT_ITEMS)
    # Excluded
    assert all(".staging" not in n and "snapshots" not in n for n in names)


def test_prune_snapshots_keeps_newest_seven(tmp_path):
    snaps = tmp_path / "bk" / "snapshots"
    snaps.mkdir(parents=True)
    # Names sort chronologically because the stamps do.
    for i in range(10):
        (snaps / f"2024010{i % 10}T0000{i:02d}Z-download.tar.gz").write_bytes(b"x")
    removed = prune_snapshots(snaps, keep=7)
    remaining = sorted(p.name for p in snaps.iterdir())
    assert len(remaining) == 7
    assert len(removed) == 3


def test_prune_snapshots_noop_under_keep(tmp_path):
    snaps = tmp_path / "bk" / "snapshots"
    snaps.mkdir(parents=True)
    (snaps / "20240101T000000Z-download.tar.gz").write_bytes(b"x")
    assert prune_snapshots(snaps, keep=7) == []


def test_create_snapshot_stamps_are_monotone(tmp_path):
    data_dir = tmp_path / "data"
    snapshots_dir = tmp_path / "bk" / "snapshots"
    _populate(data_dir)
    a = create_snapshot(data_dir, snapshots_dir, "download")
    time.sleep(1.1)  # ensure stamp difference (UTC seconds resolution)
    b = create_snapshot(data_dir, snapshots_dir, "download")
    assert a.name < b.name


def test_create_snapshot_no_partial_on_failure(tmp_path, monkeypatch):
    """If the archive write fails mid-way, no .tar.gz is left in snapshots/."""
    data_dir = tmp_path / "data"
    snapshots_dir = tmp_path / "bk" / "snapshots"
    _populate(data_dir)

    from cli.data import snapshots

    real_add = tarfile.TarFile.add

    def boom(self, *args, **kwargs):
        real_add(self, *args, **kwargs)  # add the first entry
        raise RuntimeError("disk full")

    monkeypatch.setattr(tarfile.TarFile, "add", boom)

    import pytest as _pt

    with _pt.raises(RuntimeError, match="disk full"):
        snapshots.create_snapshot(data_dir, snapshots_dir, "download")

    # Neither the final archive nor a .tmp file remains
    assert not list(snapshots_dir.glob("*.tar.gz"))
    assert not list(snapshots_dir.glob("*.tmp"))


def test_prune_snapshots_missing_dir_returns_empty(tmp_path):
    """prune_snapshots returns [] when snapshots/ doesn't exist."""
    from cli.data.snapshots import prune_snapshots

    assert prune_snapshots(tmp_path / "bk" / "snapshots", keep=7) == []
