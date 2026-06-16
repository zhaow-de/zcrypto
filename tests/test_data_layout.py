from pathlib import Path

from cli.data.layout import DatasetPaths


def test_dataset_paths_derived_locations():
    paths = DatasetPaths(data_dir=Path("/repo/data"), backup_dir=Path("/ext/bk"))
    assert paths.raw_root == Path("/ext/bk/raw")
    assert paths.snapshots_dir == Path("/ext/bk/snapshots")
    # staging + marker stay on data_dir (same-FS atomic-rename invariant)
    assert paths.staging == Path("/repo/data/.staging")
    assert paths.marker == Path("/repo/data/.commit-in-progress")


def test_dataset_paths_is_frozen():
    paths = DatasetPaths(data_dir=Path("a"), backup_dir=Path("b"))
    import dataclasses

    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        paths.data_dir = Path("c")
