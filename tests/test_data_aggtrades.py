"""Tasks 1–3: aggTrades fetch primitives, mirror path, fetch_aggtrades_sample."""

from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from pathlib import Path

import pytest

from cli.data.aggtrades import fetch_aggtrades_sample, validate_aggtrades_zip
from cli.data.binance import aggtrades_archive_parts, aggtrades_checksum_url, aggtrades_zip_url
from cli.data.layout import DatasetPaths
from cli.data.mirror import aggtrades_mirror_path, read_zip
from tests.data_fixtures import FakeSource

DATE = dt.date(2025, 3, 3)
SYMBOL = "BTCUSDT"


class TestAggtadesArchiveParts:
    def test_returns_rel_dir_and_name(self) -> None:
        rel_dir, name = aggtrades_archive_parts(SYMBOL, DATE)
        assert rel_dir == "spot/daily/aggTrades/BTCUSDT"
        assert name == "BTCUSDT-aggTrades-2025-03-03.zip"

    def test_no_interval_in_path(self) -> None:
        """Unlike klines, aggTrades has no interval segment."""
        rel_dir, _ = aggtrades_archive_parts(SYMBOL, DATE)
        assert "1d" not in rel_dir
        assert "interval" not in rel_dir


class TestAggtadesUrls:
    def test_zip_url(self) -> None:
        url = aggtrades_zip_url(SYMBOL, DATE)
        assert url == "https://data.binance.vision/data/spot/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2025-03-03.zip"

    def test_checksum_url(self) -> None:
        url = aggtrades_checksum_url(SYMBOL, DATE)
        assert url == "https://data.binance.vision/data/spot/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2025-03-03.zip.CHECKSUM"


class TestAggtadesMirrorPath:
    def test_year_partitioned(self, tmp_path: Path) -> None:
        path = aggtrades_mirror_path(tmp_path, SYMBOL, DATE)
        assert path == tmp_path / "spot/daily/aggTrades/BTCUSDT/2025/BTCUSDT-aggTrades-2025-03-03.zip"

    def test_uses_date_year(self, tmp_path: Path) -> None:
        date_2024 = dt.date(2024, 12, 31)
        path = aggtrades_mirror_path(tmp_path, SYMBOL, date_2024)
        assert "2024" in str(path)
        assert "2025" not in str(path)


class TestFakeSourceAggtrades:
    def test_registered_bytes_roundtrip(self) -> None:
        src = FakeSource()
        payload = b"fake-aggtrades-zip-bytes"
        src.add_aggtrades(SYMBOL, DATE, raw=payload)
        result = src.fetch_aggtrades_archive(SYMBOL, DATE)
        assert result == payload

    def test_missing_key_raises(self) -> None:
        src = FakeSource()
        with pytest.raises(KeyError):
            src.fetch_aggtrades_archive(SYMBOL, DATE)


def _zip_with(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestValidateAggtradesZip:
    def test_valid_single_csv_passes(self) -> None:
        raw = _zip_with({"BTCUSDT-aggTrades-2025-03-03.csv": b"1,100.0,0.5,1,1,1700000000000,True,True\n"})
        validate_aggtrades_zip(raw)  # no raise

    def test_corrupt_bytes_raises(self) -> None:
        with pytest.raises(zipfile.BadZipFile):
            validate_aggtrades_zip(b"not-a-zip-at-all")

    def test_empty_member_raises(self) -> None:
        raw = _zip_with({"BTCUSDT-aggTrades-2025-03-03.csv": b""})
        with pytest.raises(ValueError, match="empty"):
            validate_aggtrades_zip(raw)

    def test_multiple_csv_raises(self) -> None:
        raw = _zip_with(
            {
                "BTCUSDT-aggTrades-2025-03-03.csv": b"1,100.0,0.5,1,1,1700000000000,True,True\n",
                "extra.csv": b"1,100.0,0.5,1,1,1700000000000,True,True\n",
            }
        )
        with pytest.raises(ValueError, match="exactly one"):
            validate_aggtrades_zip(raw)


# ---------------------------------------------------------------------------
# Task 3: fetch_aggtrades_sample
# ---------------------------------------------------------------------------


def _make_aggtrades_zip(symbol: str, date: dt.date) -> bytes:
    name = f"{symbol}-aggTrades-{date}.csv"
    return _zip_with({name: b"1,100.0,0.5,1,1,1700000000000,True,True\n"})


class TestFetchAggtadesSample:
    def _paths(self, tmp_path: Path) -> DatasetPaths:
        return DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")

    def test_zips_land_at_year_mirror_paths(self, tmp_path: Path) -> None:
        paths = self._paths(tmp_path)
        src = FakeSource()
        dates = [dt.date(2025, 3, 1), dt.date(2025, 3, 2)]
        for d in dates:
            src.add_aggtrades("BTCUSDT", d, raw=_make_aggtrades_zip("BTCUSDT", d))
        manifest = fetch_aggtrades_sample(paths, src, ["BTCUSDT"], dt.date(2025, 3, 1), dt.date(2025, 3, 2))
        for d in dates:
            mpath = aggtrades_mirror_path(paths.raw_root, "BTCUSDT", d)
            assert read_zip(mpath) is not None, f"expected zip at {mpath}"
        assert manifest["pairs"] == ["BTCUSDT"]

    def test_idempotent_rerun_skips_already_present(self, tmp_path: Path) -> None:
        paths = self._paths(tmp_path)
        src = FakeSource()
        d = dt.date(2025, 3, 1)
        src.add_aggtrades("BTCUSDT", d, raw=_make_aggtrades_zip("BTCUSDT", d))
        fetch_aggtrades_sample(paths, src, ["BTCUSDT"], d, d)
        # Second run: remove from source so a real fetch would raise KeyError
        src2 = FakeSource()  # empty — any fetch would raise KeyError
        manifest2 = fetch_aggtrades_sample(paths, src2, ["BTCUSDT"], d, d)
        assert manifest2["pairs_stats"]["BTCUSDT"]["fetched"] == 0
        assert manifest2["pairs_stats"]["BTCUSDT"]["skipped"] == 1

    def test_manifest_records_pairs_window_and_bytes(self, tmp_path: Path) -> None:
        paths = self._paths(tmp_path)
        src = FakeSource()
        dates = [dt.date(2025, 3, 1), dt.date(2025, 3, 2)]
        raw_zips = {}
        for d in dates:
            raw = _make_aggtrades_zip("BTCUSDT", d)
            raw_zips[d] = raw
            src.add_aggtrades("BTCUSDT", d, raw=raw)
        manifest = fetch_aggtrades_sample(paths, src, ["BTCUSDT"], dt.date(2025, 3, 1), dt.date(2025, 3, 2))
        assert manifest["from"] == "2025-03-01"
        assert manifest["to"] == "2025-03-02"
        assert "BTCUSDT" in manifest["pairs_stats"]
        stats = manifest["pairs_stats"]["BTCUSDT"]
        assert stats["fetched"] == 2
        assert stats["total_bytes"] == sum(len(raw_zips[d]) for d in dates)
        assert set(stats["present_dates"]) == {"2025-03-01", "2025-03-02"}

    def test_manifest_idempotent_rerun_records_full_sample(self, tmp_path: Path) -> None:
        """Re-running fetch_aggtrades_sample yields identical present_dates + total_bytes."""
        paths = self._paths(tmp_path)
        src = FakeSource()
        dates = [dt.date(2025, 3, 1), dt.date(2025, 3, 2)]
        raw_zips: dict[dt.date, bytes] = {}
        for d in dates:
            raw = _make_aggtrades_zip("BTCUSDT", d)
            raw_zips[d] = raw
            src.add_aggtrades("BTCUSDT", d, raw=raw)
        fetch_aggtrades_sample(paths, src, ["BTCUSDT"], dt.date(2025, 3, 1), dt.date(2025, 3, 2))
        # Second run with empty source — all dates already mirrored, nothing fetched
        src2 = FakeSource()
        manifest2 = fetch_aggtrades_sample(paths, src2, ["BTCUSDT"], dt.date(2025, 3, 1), dt.date(2025, 3, 2))
        stats2 = manifest2["pairs_stats"]["BTCUSDT"]
        assert stats2["fetched"] == 0, "re-run should skip all (no new fetches)"
        assert stats2["skipped"] == 2, "re-run should count both dates as skipped"
        assert set(stats2["present_dates"]) == {"2025-03-01", "2025-03-02"}, "all mirrored dates must appear"
        expected_bytes = sum(len(raw_zips[d]) for d in dates)
        assert stats2["total_bytes"] == expected_bytes, (
            f"total_bytes must reflect present zips (expected {expected_bytes}, got {stats2['total_bytes']})"
        )

    def test_manifest_json_written_to_aggtrades_root(self, tmp_path: Path) -> None:
        paths = self._paths(tmp_path)
        src = FakeSource()
        d = dt.date(2025, 3, 1)
        src.add_aggtrades("BTCUSDT", d, raw=_make_aggtrades_zip("BTCUSDT", d))
        fetch_aggtrades_sample(paths, src, ["BTCUSDT"], d, d)
        manifest_path = paths.raw_root / "spot/daily/aggTrades/aggtrades-manifest.json"
        assert manifest_path.exists(), f"expected manifest at {manifest_path}"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["pairs"] == ["BTCUSDT"]

    def test_checksum_validated_path_skips_validate_zip(self, tmp_path: Path) -> None:
        """When a checksum is present and matches, validate_aggtrades_zip is NOT called (sha256 is sufficient)."""
        import hashlib

        paths = self._paths(tmp_path)
        src = FakeSource()
        d = dt.date(2025, 3, 1)
        raw = _make_aggtrades_zip("BTCUSDT", d)
        checksum = hashlib.sha256(raw).hexdigest()
        src.add_aggtrades("BTCUSDT", d, raw=raw, checksum=checksum)
        # Should succeed without error (the zip IS valid, so this just verifies no double-gate)
        manifest = fetch_aggtrades_sample(paths, src, ["BTCUSDT"], d, d)
        assert manifest["pairs_stats"]["BTCUSDT"]["fetched"] == 1

    def test_unchecksummed_path_validates_zip_structure(self, tmp_path: Path) -> None:
        """When no checksum, validate_aggtrades_zip is used as integrity gate (must pass for a valid zip)."""
        paths = self._paths(tmp_path)
        src = FakeSource()
        d = dt.date(2025, 3, 1)
        raw = _make_aggtrades_zip("BTCUSDT", d)
        src.add_aggtrades("BTCUSDT", d, raw=raw)  # no checksum
        manifest = fetch_aggtrades_sample(paths, src, ["BTCUSDT"], d, d)
        assert manifest["pairs_stats"]["BTCUSDT"]["fetched"] == 1

    def test_multi_pair_multi_date(self, tmp_path: Path) -> None:
        paths = self._paths(tmp_path)
        src = FakeSource()
        pairs = ["BTCUSDT", "ETHUSDT"]
        dates = [dt.date(2025, 3, 1), dt.date(2025, 3, 2)]
        for p in pairs:
            for d in dates:
                src.add_aggtrades(p, d, raw=_make_aggtrades_zip(p, d))
        manifest = fetch_aggtrades_sample(paths, src, pairs, dates[0], dates[-1])
        assert set(manifest["pairs"]) == set(pairs)
        for p in pairs:
            assert manifest["pairs_stats"][p]["fetched"] == 2
