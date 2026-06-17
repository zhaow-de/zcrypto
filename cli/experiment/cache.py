"""Fingerprint-based cache busting for the qlib on-disk feature/dataset cache.

The fingerprint is the sha256 of <data_dir>/index.json.  When the index changes
(new download or backfill), the stored fingerprint will no longer match and the
qlib cache directories are wiped so qlib starts fresh.

Qlib writes its DiskExpressionCache to <data_dir>/features_cache and its
DiskDatasetCache to <data_dir>/dataset_cache when initialised with those backends.
The fingerprint is stored at <data_dir>/.experiment_cache_fingerprint — a top-level
dotfile that lives outside the cache dirs so it survives the wipe.

Typical call sequence (experiment run):
    ensure_cache_fresh(data_dir)   # wipe if stale
    qlib.init(...)                 # qlib rebuilds its cache as needed
    record_fingerprint(data_dir)   # stamp the new fingerprint
"""

import os
import shutil
import tempfile
from pathlib import Path

from cli.data.index import compute_sha256

# The subdirectory names qlib creates under data_dir for its two disk caches.
QLIB_CACHE_DIRS = ("features_cache", "dataset_cache")

_FINGERPRINT_FILE = ".experiment_cache_fingerprint"


def _index_path(data_dir: Path) -> Path:
    return data_dir / "index.json"


def _fingerprint_path(data_dir: Path) -> Path:
    return data_dir / _FINGERPRINT_FILE


def ensure_cache_fresh(data_dir: Path, *, refresh: bool = False) -> None:
    """Wipe qlib's cache directories if the index fingerprint has changed or *refresh* is True.

    Wipes ``<data_dir>/features_cache`` and ``<data_dir>/dataset_cache`` — the real
    directories that qlib's DiskExpressionCache / DiskDatasetCache write to.

    No-ops when ``<data_dir>/index.json`` does not exist (nothing to fingerprint).
    Does NOT write a new fingerprint — call :func:`record_fingerprint` after qlib
    has repopulated the cache.
    """
    index = _index_path(data_dir)
    if not index.exists():
        return

    current = compute_sha256(index)

    fp_file = _fingerprint_path(data_dir)
    stored: str | None = fp_file.read_text().strip() if fp_file.exists() else None

    if refresh or stored != current:
        for cache_dir_name in QLIB_CACHE_DIRS:
            shutil.rmtree(data_dir / cache_dir_name, ignore_errors=True)


def record_fingerprint(data_dir: Path) -> None:
    """Write the current index.json sha256 into the cache fingerprint file.

    Call this *after* qlib has populated the cache so the fingerprint always
    reflects content that matches the on-disk cache state.

    No-ops when ``<data_dir>/index.json`` does not exist.
    """
    index = _index_path(data_dir)
    if not index.exists():
        return

    sha = compute_sha256(index)
    fp_file = _fingerprint_path(data_dir)

    # Atomic write: write to a temp file in the same directory, then replace.
    fd, tmp_path = tempfile.mkstemp(dir=data_dir, prefix=".fp_tmp_")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(sha)
        os.replace(tmp_path, fp_file)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
