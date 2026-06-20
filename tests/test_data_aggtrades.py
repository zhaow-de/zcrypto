"""Task 1: aggTrades fetch primitives + year-partitioned mirror path."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from cli.data.binance import aggtrades_archive_parts, aggtrades_checksum_url, aggtrades_zip_url
from cli.data.mirror import aggtrades_mirror_path
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
