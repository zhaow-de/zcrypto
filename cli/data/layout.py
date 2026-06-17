from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_COMMIT_MARKER_NAME = ".commit-in-progress"
_STAGING_NAME = ".staging"


@dataclass(frozen=True)
class DatasetPaths:
    """Two-root layout: compiled dataset (data_dir) + durable backup (backup_dir).

    The compiled dataset, the staging dir, and the commit marker all live on
    `data_dir` so the atomic commit's `shutil.move(staging -> live)` stays a
    same-filesystem rename. Only the zip mirror (`raw/`) and rollback archives
    (`snapshots/`) live on `backup_dir`.
    """

    data_dir: Path
    backup_dir: Path

    @property
    def raw_root(self) -> Path:
        return self.backup_dir / "raw"

    @property
    def snapshots_dir(self) -> Path:
        return self.backup_dir / "snapshots"

    @property
    def staging(self) -> Path:
        return self.data_dir / _STAGING_NAME

    @property
    def marker(self) -> Path:
        return self.data_dir / _COMMIT_MARKER_NAME
