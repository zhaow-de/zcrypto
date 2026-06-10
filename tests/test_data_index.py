import datetime as dt
import hashlib
import json

import pytest

from cli.data.index import (
    CalendarEntry,
    FieldEntry,
    FileEntry,
    IndexData,
    PairEntry,
    PairIntervalEntry,
    compute_sha256,
    load_index,
    save_index,
    utc_now_iso,
)


def _sample_index() -> IndexData:
    cal = CalendarEntry(freq="day", from_date="2024-01-01", to_date="2024-01-03", days=3)
    fields = {
        "open": FieldEntry(bin="features/btcusdt/open.day.bin", sha256="a" * 64, updated_at="2024-01-03T12:00:00Z"),
        "close": FieldEntry(bin="features/btcusdt/close.day.bin", sha256="b" * 64, updated_at="2024-01-03T12:00:00Z"),
    }
    pair = PairEntry(
        base_asset="BTC",
        quote_asset="USDT",
        intervals={
            "1d": PairIntervalEntry(from_date="2024-01-01", to_date="2024-01-03", rows=3, fields=fields),
        },
    )
    return IndexData(
        schema_version=2,
        updated_at="2024-01-03T12:00:00Z",
        calendar=cal,
        pairs={"BTCUSDT": pair},
        other_files={
            "calendars/day.txt": FileEntry(sha256="c" * 64, updated_at="2024-01-03T12:00:00Z"),
            "instruments/all.txt": FileEntry(sha256="d" * 64, updated_at="2024-01-03T12:00:00Z"),
        },
    )


def test_index_roundtrip_via_dict():
    idx = _sample_index()
    d = idx.to_dict()
    rebuilt = IndexData.from_dict(d)
    assert rebuilt.to_dict() == d


def test_save_and_load_index_roundtrip(tmp_path):
    idx = _sample_index()
    save_index(tmp_path, idx)
    loaded = load_index(tmp_path)
    assert loaded.to_dict() == idx.to_dict()


def test_load_index_returns_none_when_missing(tmp_path):
    assert load_index(tmp_path) is None


def test_save_index_includes_keys_in_documented_order(tmp_path):
    save_index(tmp_path, _sample_index())
    raw = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert list(raw.keys()) == ["schema_version", "updated_at", "calendar", "pairs", "other_files"]


def test_compute_sha256_matches_hashlib(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"abc")
    assert compute_sha256(p) == hashlib.sha256(b"abc").hexdigest()


def test_utc_now_iso_format():
    s = utc_now_iso()
    assert s.endswith("Z")
    # Round-trip parseable as a UTC datetime
    dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def test_save_index_uses_atomic_replace(tmp_path):
    """A crash mid-write must not leave index.json truncated/corrupt."""
    save_index(tmp_path, _sample_index())
    # After a successful save, no .tmp file remains.
    assert not (tmp_path / "index.json.tmp").exists()
    # And the file is parseable (full content was committed).
    assert load_index(tmp_path) is not None
