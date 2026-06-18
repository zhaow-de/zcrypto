from __future__ import annotations

import datetime as dt
import os
import tarfile
from pathlib import Path

from cli.data.config import SNAPSHOT_KEEP

SNAPSHOT_ITEMS: tuple[str, ...] = ("calendars", "instruments", "features", "index.json")


def create_snapshot(data_dir: Path, snapshots_dir: Path, command: str) -> Path:
    """Pack the compiled dataset files into `<snapshots_dir>/<stamp>-<cmd>.tar.gz` atomically."""
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = snapshots_dir / f"{stamp}-{command}.tar.gz"
    tmp = archive.with_suffix(archive.suffix + ".tmp")
    try:
        with tarfile.open(tmp, "w:gz") as tar:
            for name in SNAPSHOT_ITEMS:
                p = data_dir / name
                if p.exists():
                    tar.add(p, arcname=name)
        os.replace(tmp, archive)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return archive


def prune_snapshots(snapshots_dir: Path, keep: int = SNAPSHOT_KEEP) -> list[Path]:
    """Keep newest `keep` archives in `snapshots_dir`; remove older. Return removed paths."""
    if not snapshots_dir.is_dir():
        return []
    archives = sorted(snapshots_dir.glob("*.tar.gz"))
    if len(archives) <= keep:
        return []
    removed = archives[: len(archives) - keep]
    for p in removed:
        p.unlink()
    return removed
