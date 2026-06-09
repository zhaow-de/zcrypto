from __future__ import annotations

import datetime as dt
import tarfile
from pathlib import Path

from cli.data.config import SNAPSHOT_KEEP

SNAPSHOT_ITEMS: tuple[str, ...] = ("calendars", "instruments", "features", "index.json")


def create_snapshot(out_dir: Path, command: str) -> Path:
    """Pack the relevant dataset files into `<out_dir>/.snapshots/<stamp>-<cmd>.tar.gz`."""
    snap_dir = out_dir / ".snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = snap_dir / f"{stamp}-{command}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name in SNAPSHOT_ITEMS:
            p = out_dir / name
            if p.exists():
                tar.add(p, arcname=name)
    return archive


def prune_snapshots(out_dir: Path, keep: int = SNAPSHOT_KEEP) -> list[Path]:
    """Keep newest `keep` archives in `<out_dir>/.snapshots/`; remove older. Return removed paths."""
    snap_dir = out_dir / ".snapshots"
    if not snap_dir.is_dir():
        return []
    archives = sorted(snap_dir.glob("*.tar.gz"))
    if len(archives) <= keep:
        return []
    removed = archives[: len(archives) - keep]
    for p in removed:
        p.unlink()
    return removed
