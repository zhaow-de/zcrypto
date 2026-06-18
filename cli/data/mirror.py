"""Local mirror of downloaded Binance zip archives.

A fetched-and-verified zip is saved under a directory tree that mirrors the remote
archive layout (plus a year subdir); a later run reads it from disk instead of
re-downloading, so a partial/failed download recovers cheaply. The mirror is trusted
without re-checksumming, so writes are atomic and reads never see a partial file.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from cli.data.binance import kline_archive_parts
from cli.data.layout import DatasetPaths


def root_for(paths: DatasetPaths) -> Path:
    """Mirror root for a dataset: ``<backup_dir>/raw`` (``DatasetPaths.raw_root``).

    The downloaded-zip mirror lives in the external backup dir (durable, the
    expensive-to-reacquire artifact), separate from the compiled dataset.
    ``DatasetPaths`` is the single source of truth for this path.
    """
    return paths.raw_root


def mirror_path(root: Path, symbol: str, interval: str, date: dt.date) -> Path:
    """Local path for a daily kline zip: ``<root>/<archive-dir>/<YYYY>/<file>.zip``.

    Reuses ``kline_archive_parts`` — the same builder the remote URL uses — so the local
    layout cannot drift from the remote one. The ``<YYYY>`` subdir is the only addition.
    """
    rel_dir, name = kline_archive_parts(symbol, interval, date)
    return root / rel_dir / str(date.year) / name


def read_zip(path: Path) -> bytes | None:
    """Cached zip bytes if present (a mirror hit), else None."""
    if path.is_file():
        return path.read_bytes()
    return None


def save_zip(path: Path, data: bytes) -> None:
    """Atomically write ``data`` to ``path`` (parents created, temp file + ``os.replace``).

    Atomic because readers trust the mirror without re-checksumming — an interrupted write
    must never leave a half-written zip that a later run would read as valid.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
