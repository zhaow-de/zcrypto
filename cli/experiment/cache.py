"""Fingerprint-based cache busting for the qlib on-disk feature/dataset cache.

The fingerprint is the sha256 of <data_dir>/index.json.  When the index changes
(new download or backfill), the stored fingerprint will no longer match and the
entire cache directory is wiped so qlib starts fresh.

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

CACHE_DIRNAME = "cache"
_FINGERPRINT_FILE = ".dataset_fingerprint"


def _index_path(data_dir: Path) -> Path:
    return data_dir / "index.json"


def _cache_dir(data_dir: Path) -> Path:
    return data_dir / CACHE_DIRNAME


def _fingerprint_path(data_dir: Path) -> Path:
    return _cache_dir(data_dir) / _FINGERPRINT_FILE


def ensure_cache_fresh(data_dir: Path, *, refresh: bool = False) -> None:
    """Wipe the cache directory if the index fingerprint has changed or *refresh* is True.

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
        shutil.rmtree(_cache_dir(data_dir), ignore_errors=True)


def record_fingerprint(data_dir: Path) -> None:
    """Write the current index.json sha256 into the cache fingerprint file.

    Call this *after* qlib has populated the cache so the fingerprint always
    reflects content that matches the on-disk cache state.

    No-ops when ``<data_dir>/index.json`` does not exist.
    """
    index = _index_path(data_dir)
    if not index.exists():
        return

    cache = _cache_dir(data_dir)
    cache.mkdir(parents=True, exist_ok=True)

    sha = compute_sha256(index)
    fp_file = _fingerprint_path(data_dir)

    # Atomic write: write to a temp file in the same directory, then replace.
    fd, tmp_path = tempfile.mkstemp(dir=cache, prefix=".fp_tmp_")
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
