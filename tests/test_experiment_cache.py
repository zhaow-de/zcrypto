"""Tests for cli.experiment.cache — index.json fingerprint-based cache busting."""

import hashlib

import pytest

from cli.data.index import compute_sha256
from cli.experiment.cache import ensure_cache_fresh, record_fingerprint


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# 1. Stale wipe: stored fingerprint differs → cache dir wiped
# ---------------------------------------------------------------------------
def test_stale_fingerprint_wipes_cache(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    index_json = data_dir / "index.json"
    index_json.write_bytes(b"A")

    cache_dir = data_dir / "cache"
    cache_dir.mkdir()
    (cache_dir / ".dataset_fingerprint").write_text(_sha256_bytes(b"B"))  # wrong sha
    junk = cache_dir / "foo"
    junk.write_text("junk")

    ensure_cache_fresh(data_dir)

    # The wipe must have happened — junk file gone (proves rmtree ran)
    assert not junk.exists(), "cache/foo should have been wiped but still exists"


# ---------------------------------------------------------------------------
# 2. Fresh no-op: stored fingerprint matches → cache untouched
# ---------------------------------------------------------------------------
def test_fresh_fingerprint_leaves_cache(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    index_json = data_dir / "index.json"
    index_json.write_bytes(b"A")

    # Use record_fingerprint to plant a correct fingerprint, then add junk
    cache_dir = data_dir / "cache"
    cache_dir.mkdir()
    record_fingerprint(data_dir)

    junk = cache_dir / "foo"
    junk.write_text("junk")

    ensure_cache_fresh(data_dir)

    assert junk.exists(), "cache/foo should NOT have been wiped but it was removed"


# ---------------------------------------------------------------------------
# 3. refresh=True wipes even when fingerprint is current
# ---------------------------------------------------------------------------
def test_refresh_flag_forces_wipe(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    index_json = data_dir / "index.json"
    index_json.write_bytes(b"A")

    cache_dir = data_dir / "cache"
    cache_dir.mkdir()
    record_fingerprint(data_dir)

    junk = cache_dir / "foo"
    junk.write_text("junk")

    ensure_cache_fresh(data_dir, refresh=True)

    assert not junk.exists(), "cache/foo should have been wiped by refresh=True but still exists"


# ---------------------------------------------------------------------------
# 4. Missing cache dir: must not raise
# ---------------------------------------------------------------------------
def test_missing_cache_dir_no_raise(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "index.json").write_bytes(b"A")
    # no cache/ dir

    ensure_cache_fresh(data_dir)  # should not raise


# ---------------------------------------------------------------------------
# 5. record_fingerprint writes the correct sha
# ---------------------------------------------------------------------------
def test_record_fingerprint_writes_correct_sha(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    index_json = data_dir / "index.json"
    index_json.write_bytes(b"hello world")

    (data_dir / "cache").mkdir()
    record_fingerprint(data_dir)

    fp_file = data_dir / "cache" / ".dataset_fingerprint"
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
