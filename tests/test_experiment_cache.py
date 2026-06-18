"""Tests for cli.experiment.cache — index.json fingerprint-based cache busting."""

import hashlib

import pytest

from cli.data.index import compute_sha256
from cli.experiment.cache import ensure_cache_fresh, record_fingerprint


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# 1. Stale wipe: stored fingerprint differs → BOTH qlib cache dirs wiped
# ---------------------------------------------------------------------------
def test_stale_fingerprint_wipes_cache(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    index_json = data_dir / "index.json"
    index_json.write_bytes(b"A")

    # Plant stale fingerprint
    (data_dir / ".experiment_cache_fingerprint").write_text(_sha256_bytes(b"B"))  # wrong sha

    # Put junk in BOTH real qlib cache dirs
    features_cache = data_dir / "features_cache"
    features_cache.mkdir()
    junk_f = features_cache / "foo"
    junk_f.write_text("junk")

    dataset_cache = data_dir / "dataset_cache"
    dataset_cache.mkdir()
    junk_d = dataset_cache / "bar"
    junk_d.write_text("junk")

    ensure_cache_fresh(data_dir)

    # Both dirs must be gone (proves rmtree targeted the right paths)
    assert not junk_f.exists(), "features_cache/foo should have been wiped but still exists"
    assert not junk_d.exists(), "dataset_cache/bar should have been wiped but still exists"
    assert not features_cache.exists(), "features_cache should have been removed entirely"
    assert not dataset_cache.exists(), "dataset_cache should have been removed entirely"


# ---------------------------------------------------------------------------
# 2. Fresh no-op: stored fingerprint matches → cache untouched
# ---------------------------------------------------------------------------
def test_fresh_fingerprint_leaves_cache(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    index_json = data_dir / "index.json"
    index_json.write_bytes(b"A")

    # Plant correct fingerprint, then add junk in features_cache
    record_fingerprint(data_dir)

    features_cache = data_dir / "features_cache"
    features_cache.mkdir()
    junk = features_cache / "foo"
    junk.write_text("junk")

    ensure_cache_fresh(data_dir)

    assert junk.exists(), "features_cache/foo should NOT have been wiped but it was removed"


# ---------------------------------------------------------------------------
# 3. refresh=True wipes even when fingerprint is current
# ---------------------------------------------------------------------------
def test_refresh_flag_forces_wipe(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    index_json = data_dir / "index.json"
    index_json.write_bytes(b"A")

    record_fingerprint(data_dir)

    features_cache = data_dir / "features_cache"
    features_cache.mkdir()
    junk = features_cache / "foo"
    junk.write_text("junk")

    ensure_cache_fresh(data_dir, refresh=True)

    assert not junk.exists(), "features_cache/foo should have been wiped by refresh=True but still exists"


# ---------------------------------------------------------------------------
# 4. Missing cache dirs: must not raise
# ---------------------------------------------------------------------------
def test_missing_cache_dirs_no_raise(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "index.json").write_bytes(b"A")
    # no features_cache/ or dataset_cache/

    ensure_cache_fresh(data_dir)  # should not raise


# ---------------------------------------------------------------------------
# 5. record_fingerprint writes the correct sha to top-level dotfile
# ---------------------------------------------------------------------------
def test_record_fingerprint_writes_correct_sha(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    index_json = data_dir / "index.json"
    index_json.write_bytes(b"hello world")

    record_fingerprint(data_dir)

    fp_file = data_dir / ".experiment_cache_fingerprint"
    assert fp_file.exists()
    stored = fp_file.read_text().strip()
    expected = compute_sha256(index_json)
    assert stored == expected


# ---------------------------------------------------------------------------
# 6. Missing index.json: both functions no-op (no raise)
# ---------------------------------------------------------------------------
def test_missing_index_json_no_raise(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # deliberately no index.json

    ensure_cache_fresh(data_dir)  # should not raise
    record_fingerprint(data_dir)  # should not raise
