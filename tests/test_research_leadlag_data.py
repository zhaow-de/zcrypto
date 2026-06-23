"""Tests for cli/research/leadlag/data.py — 1h-kline fetcher-reader (iter-51 lead-lag probe).

TDD: parser unit tests + fetch_1h_klines integration tests (monkeypatched network).
No real network is used — all fetches go through patched _pool.request or _retryable_request.
"""

from __future__ import annotations

import datetime as dt
import io
import socket
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pandas as pd
import pytest

from cli.config import FetchConfig
from cli.data.binance import HttpStatusError, _pool
from cli.research.leadlag.data import _CONTRACT_COLS, fetch_1h_klines, parse_1h_kline_zip


@pytest.fixture(autouse=True)
def _restore_socket_default_timeout():
    """fetch_1h_klines calls socket.setdefaulttimeout() process-wide (the stale-keepalive
    hang backstop). Save/restore it so these tests never leak the global default into the
    rest of the suite. Mirrors the same fixture in test_data_binance.py."""
    prev = socket.getdefaulttimeout()
    try:
        yield
    finally:
        socket.setdefaulttimeout(prev)


# ---------------------------------------------------------------------------
# Helpers: synthetic 1h kline zip builders
# ---------------------------------------------------------------------------


def _make_1h_kline_csv(date: dt.date, *, precision: str = "ms", with_header: bool = False) -> bytes:
    """Build a 24-row Binance 1h kline CSV for the given UTC date.

    precision: "ms" → open_time in milliseconds (< 2025-01-01 archives)
               "us" → open_time in microseconds (>= 2025-01-01 archives)
    with_header: prepend the 12-column header row (recent archive format).
    """
    midnight = dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc)
    rows: list[str] = []
    for h in range(24):
        bar_open = midnight + dt.timedelta(hours=h)
        bar_close = bar_open + dt.timedelta(hours=1) - dt.timedelta(milliseconds=1)
        epoch_s_open = int(bar_open.timestamp())
        epoch_s_close = int(bar_close.timestamp())
        if precision == "ms":
            open_t = epoch_s_open * 1_000
            close_t = epoch_s_close * 1_000
        elif precision == "us":
            open_t = epoch_s_open * 1_000_000
            close_t = epoch_s_close * 1_000_000
        else:
            raise ValueError(f"unknown precision {precision!r}")
        open_ = 100.0 + h
        high = open_ * 1.01
        low = open_ * 0.99
        close = open_ * 1.005
        volume = 50.0 + h
        quote_vol = volume * (open_ + close) / 2.0
        rows.append(f"{open_t},{open_},{high},{low},{close},{volume},{close_t},{quote_vol},100,{volume * 0.5},{quote_vol * 0.5},0")

    header = "open_time,open,high,low,close,volume,close_time,quote_asset_volume,count,taker_buy_base_volume,taker_buy_quote_volume,ignore\n"
    body = "\n".join(rows) + "\n"
    csv_text = (header + body) if with_header else body
    return csv_text.encode()


def _make_1h_kline_zip(date: dt.date, symbol: str = "BTCUSDT", *, precision: str = "ms", with_header: bool = False) -> bytes:
    """Pack a synthetic 24-row 1h kline CSV into a zip (matching Binance archive layout)."""
    csv_bytes = _make_1h_kline_csv(date, precision=precision, with_header=with_header)
    inner_name = f"{symbol}-1h-{date}.csv"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, csv_bytes)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# parse_1h_kline_zip: row count, schema, dtypes
# ---------------------------------------------------------------------------


class TestParse1hKlineZip:
    def test_returns_24_rows(self):
        raw = _make_1h_kline_zip(dt.date(2024, 3, 15), "BTCUSDT")
        df = parse_1h_kline_zip(raw, "BTCUSDT")
        assert len(df) == 24

    def test_contract_columns_present(self):
        raw = _make_1h_kline_zip(dt.date(2024, 3, 15), "ETHUSDT")
        df = parse_1h_kline_zip(raw, "ETHUSDT")
        assert list(df.columns) == _CONTRACT_COLS

    def test_timestamp_open_utc_is_tz_aware_utc(self):
        raw = _make_1h_kline_zip(dt.date(2024, 3, 15), "BTCUSDT")
        df = parse_1h_kline_zip(raw, "BTCUSDT")
        ts = df["timestamp_open_utc"].iloc[0]
        assert ts.tzinfo is not None
        assert str(ts.tzinfo) == "UTC"

    def test_timestamps_are_hourly_and_ordered(self):
        date = dt.date(2024, 3, 15)
        raw = _make_1h_kline_zip(date, "BTCUSDT")
        df = parse_1h_kline_zip(raw, "BTCUSDT")
        midnight = pd.Timestamp(dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc))
        for i, row in df.iterrows():
            expected = midnight + pd.Timedelta(hours=i)
            assert row["timestamp_open_utc"] == expected, f"row {i}: expected {expected}, got {row['timestamp_open_utc']}"

    def test_symbol_column_matches_argument(self):
        raw = _make_1h_kline_zip(dt.date(2024, 3, 15), "SOLUSDT")
        df = parse_1h_kline_zip(raw, "SOLUSDT")
        assert (df["symbol"] == "SOLUSDT").all()

    def test_ohlcv_are_float64(self):
        raw = _make_1h_kline_zip(dt.date(2024, 3, 15), "BTCUSDT")
        df = parse_1h_kline_zip(raw, "BTCUSDT")
        for col in ("open", "high", "low", "close", "volume"):
            assert df[col].dtype == "float64", f"{col} dtype should be float64, got {df[col].dtype}"


# ---------------------------------------------------------------------------
# parse_1h_kline_zip: ms/µs auto-detection
# ---------------------------------------------------------------------------


class TestParse1hKlineZipUnitAutoDetect:
    @pytest.mark.parametrize("precision", ["ms", "us"])
    def test_correct_hours_for_both_precisions(self, precision: str):
        """Per-row ms/µs auto-detect: both land at the correct UTC hours."""
        date = dt.date(2024, 12, 31)
        raw = _make_1h_kline_zip(date, "BTCUSDT", precision=precision)
        df = parse_1h_kline_zip(raw, "BTCUSDT")
        assert len(df) == 24
        midnight = pd.Timestamp(dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc))
        for i, row in df.iterrows():
            expected = midnight + pd.Timedelta(hours=i)
            assert row["timestamp_open_utc"] == expected, (
                f"precision={precision}, row {i}: expected {expected}, got {row['timestamp_open_utc']}"
            )

    def test_ms_epoch_lands_at_correct_hour(self):
        """Millisecond epoch (pre-2025): verify hour 0 and hour 23 specifically."""
        date = dt.date(2024, 6, 1)
        raw = _make_1h_kline_zip(date, "ETHUSDT", precision="ms")
        df = parse_1h_kline_zip(raw, "ETHUSDT")
        expected_h0 = pd.Timestamp(dt.datetime(2024, 6, 1, 0, tzinfo=dt.timezone.utc))
        expected_h23 = pd.Timestamp(dt.datetime(2024, 6, 1, 23, tzinfo=dt.timezone.utc))
        assert df["timestamp_open_utc"].iloc[0] == expected_h0
        assert df["timestamp_open_utc"].iloc[23] == expected_h23

    def test_us_epoch_lands_at_correct_hour(self):
        """Microsecond epoch (post-2025): verify hour 0 and hour 23 specifically."""
        date = dt.date(2025, 3, 1)
        raw = _make_1h_kline_zip(date, "ETHUSDT", precision="us")
        df = parse_1h_kline_zip(raw, "ETHUSDT")
        expected_h0 = pd.Timestamp(dt.datetime(2025, 3, 1, 0, tzinfo=dt.timezone.utc))
        expected_h23 = pd.Timestamp(dt.datetime(2025, 3, 1, 23, tzinfo=dt.timezone.utc))
        assert df["timestamp_open_utc"].iloc[0] == expected_h0
        assert df["timestamp_open_utc"].iloc[23] == expected_h23


# ---------------------------------------------------------------------------
# parse_1h_kline_zip: headered vs headerless
# ---------------------------------------------------------------------------


class TestParse1hKlineZipHeaderDetection:
    def test_headerless_csv_parses_24_rows(self):
        raw = _make_1h_kline_zip(dt.date(2024, 3, 15), with_header=False)
        df = parse_1h_kline_zip(raw, "BTCUSDT")
        assert len(df) == 24

    def test_headered_csv_parses_24_rows_not_25(self):
        """Header row must be skipped — result is 24 data rows, not 25."""
        raw = _make_1h_kline_zip(dt.date(2024, 3, 15), with_header=True)
        df = parse_1h_kline_zip(raw, "BTCUSDT")
        assert len(df) == 24

    def test_headered_and_headerless_same_first_timestamp(self):
        date = dt.date(2024, 3, 15)
        raw_no_hdr = _make_1h_kline_zip(date, with_header=False)
        raw_hdr = _make_1h_kline_zip(date, with_header=True)
        df_no = parse_1h_kline_zip(raw_no_hdr, "BTCUSDT")
        df_hd = parse_1h_kline_zip(raw_hdr, "BTCUSDT")
        assert df_no["timestamp_open_utc"].iloc[0] == df_hd["timestamp_open_utc"].iloc[0]


# ---------------------------------------------------------------------------
# fetch_1h_klines: assembled frame, 2 symbols x 2 days = 96 rows
# ---------------------------------------------------------------------------


class TestFetch1hKlines:
    """All tests monkeypatch _pool.request so no real network calls are made."""

    _DATE_A = dt.date(2024, 3, 1)
    _DATE_B = dt.date(2024, 3, 2)

    def _make_zip_response(self, symbol: str, date: dt.date, precision: str = "ms") -> MagicMock:
        """Return a MagicMock urllib3 response whose .data is the synthetic zip bytes."""
        raw = _make_1h_kline_zip(date, symbol, precision=precision)
        resp = MagicMock(status=200)
        resp.data = raw
        return resp

    def test_assembled_frame_has_contract_columns(self, tmp_path):
        """fetch_1h_klines returns a DataFrame with exactly the contract columns."""
        symbols = ["BTCUSDT", "ETHUSDT"]
        cache = str(tmp_path / "1h.parquet")

        def _side_effect(method, url, **kwargs):
            for sym in symbols:
                for d in (self._DATE_A, self._DATE_B):
                    if sym in url and d.strftime("%Y-%m-%d") in url:
                        return self._make_zip_response(sym, d)
            raise AssertionError(f"unexpected URL: {url}")

        with patch.object(_pool, "request", side_effect=_side_effect):
            df = fetch_1h_klines(symbols, self._DATE_A, self._DATE_B, cache_path=cache)

        assert list(df.columns) == _CONTRACT_COLS

    def test_assembled_frame_has_96_rows_2_symbols_2_days(self, tmp_path):
        """2 symbols × 2 days × 24 hours = 96 rows."""
        symbols = ["BTCUSDT", "ETHUSDT"]
        cache = str(tmp_path / "1h.parquet")

        def _side_effect(method, url, **kwargs):
            for sym in symbols:
                for d in (self._DATE_A, self._DATE_B):
                    if sym in url and d.strftime("%Y-%m-%d") in url:
                        return self._make_zip_response(sym, d)
            raise AssertionError(f"unexpected URL: {url}")

        with patch.object(_pool, "request", side_effect=_side_effect):
            df = fetch_1h_klines(symbols, self._DATE_A, self._DATE_B, cache_path=cache)

        assert len(df) == 96, f"expected 96 rows, got {len(df)}"

    def test_assembled_frame_contains_both_symbols(self, tmp_path):
        symbols = ["BTCUSDT", "ETHUSDT"]
        cache = str(tmp_path / "1h.parquet")

        def _side_effect(method, url, **kwargs):
            for sym in symbols:
                for d in (self._DATE_A, self._DATE_B):
                    if sym in url and d.strftime("%Y-%m-%d") in url:
                        return self._make_zip_response(sym, d)
            raise AssertionError(f"unexpected URL: {url}")

        with patch.object(_pool, "request", side_effect=_side_effect):
            df = fetch_1h_klines(symbols, self._DATE_A, self._DATE_B, cache_path=cache)

        assert set(df["symbol"].unique()) == {"BTCUSDT", "ETHUSDT"}

    def test_assembled_frame_sorted_by_symbol_then_timestamp(self, tmp_path):
        """Contract: sorted by (symbol, timestamp_open_utc)."""
        symbols = ["BTCUSDT", "ETHUSDT"]
        cache = str(tmp_path / "1h.parquet")

        def _side_effect(method, url, **kwargs):
            for sym in symbols:
                for d in (self._DATE_A, self._DATE_B):
                    if sym in url and d.strftime("%Y-%m-%d") in url:
                        return self._make_zip_response(sym, d)
            raise AssertionError(f"unexpected URL: {url}")

        with patch.object(_pool, "request", side_effect=_side_effect):
            df = fetch_1h_klines(symbols, self._DATE_A, self._DATE_B, cache_path=cache)

        # Verify monotone symbol+timestamp ordering.
        pairs = list(zip(df["symbol"], df["timestamp_open_utc"]))
        assert pairs == sorted(pairs), "frame is not sorted by (symbol, timestamp_open_utc)"

    def test_ohlcv_are_float64_in_assembled_frame(self, tmp_path):
        symbols = ["BTCUSDT"]
        cache = str(tmp_path / "1h.parquet")
        date = self._DATE_A

        def _side_effect(method, url, **kwargs):
            return self._make_zip_response("BTCUSDT", date)

        with patch.object(_pool, "request", side_effect=_side_effect):
            df = fetch_1h_klines(symbols, date, date, cache_path=cache)

        for col in ("open", "high", "low", "close", "volume"):
            assert df[col].dtype == "float64", f"{col} dtype should be float64"

    def test_timestamp_is_tz_aware_utc_in_assembled_frame(self, tmp_path):
        symbols = ["BTCUSDT"]
        cache = str(tmp_path / "1h.parquet")
        date = self._DATE_A

        def _side_effect(method, url, **kwargs):
            return self._make_zip_response("BTCUSDT", date)

        with patch.object(_pool, "request", side_effect=_side_effect):
            df = fetch_1h_klines(symbols, date, date, cache_path=cache)

        ts = df["timestamp_open_utc"].iloc[0]
        assert ts.tzinfo is not None and str(ts.tzinfo) == "UTC"

    def test_missing_404_day_skipped_not_fatal(self, tmp_path):
        """A 404 response for a specific day must be skipped with a warning, not raise.

        Patches _retryable_request directly so the test explicitly exercises the
        _fetch_one 404-catch block (HttpStatusError → skip + WARNING, not fatal).
        """
        symbols = ["BTCUSDT"]
        cache = str(tmp_path / "1h.parquet")

        date_a_str = self._DATE_A.strftime("%Y-%m-%d")

        def _retryable_side_effect(method, url, **kwargs):
            if date_a_str in url:
                raise HttpStatusError(404, url)
            raw = _make_1h_kline_zip(self._DATE_B, "BTCUSDT")
            resp = MagicMock(status=200)
            resp.data = raw
            return resp

        with patch("cli.research.leadlag.data._retryable_request", side_effect=_retryable_side_effect):
            df = fetch_1h_klines(symbols, self._DATE_A, self._DATE_B, cache_path=cache)

        # DATE_A was 404 → skipped; DATE_B gives 24 rows.
        assert len(df) == 24


# ---------------------------------------------------------------------------
# fetch_1h_klines: cache behaviour
# ---------------------------------------------------------------------------


class TestFetch1hKlinesCache:
    _DATE_A = dt.date(2024, 3, 1)
    _DATE_B = dt.date(2024, 3, 2)

    def _make_zip_response(self, symbol: str, date: dt.date) -> MagicMock:
        raw = _make_1h_kline_zip(date, symbol)
        resp = MagicMock(status=200)
        resp.data = raw
        return resp

    def test_second_call_loads_cache_without_fetching(self, tmp_path):
        """If cache exists, second call must NOT invoke _pool.request."""
        symbols = ["BTCUSDT", "ETHUSDT"]
        cache = str(tmp_path / "1h.parquet")

        def _side_effect(method, url, **kwargs):
            for sym in symbols:
                for d in (self._DATE_A, self._DATE_B):
                    if sym in url and d.strftime("%Y-%m-%d") in url:
                        return self._make_zip_response(sym, d)
            raise AssertionError(f"unexpected URL: {url}")

        # First call: populate the cache.
        with patch.object(_pool, "request", side_effect=_side_effect) as mock_req:
            df1 = fetch_1h_klines(symbols, self._DATE_A, self._DATE_B, cache_path=cache)
            first_call_count = mock_req.call_count
        assert first_call_count > 0, "first call should hit the network"

        # Second call: cache must be used, network must not be called.
        with patch.object(_pool, "request") as mock_req2:
            df2 = fetch_1h_klines(symbols, self._DATE_A, self._DATE_B, cache_path=cache)
            assert mock_req2.call_count == 0, "second call must not re-fetch when cache exists"

        # Both calls should return identical frames.
        pd.testing.assert_frame_equal(df1.reset_index(drop=True), df2.reset_index(drop=True))

    def test_cache_file_is_created_on_first_call(self, tmp_path):
        """After the first fetch, the cache file must exist on disk."""
        symbols = ["BTCUSDT"]
        cache = str(tmp_path / "subdir" / "1h.parquet")

        def _side_effect(method, url, **kwargs):
            return self._make_zip_response("BTCUSDT", self._DATE_A)

        with patch.object(_pool, "request", side_effect=_side_effect):
            fetch_1h_klines(symbols, self._DATE_A, self._DATE_A, cache_path=cache)

        assert Path(cache).exists(), "cache file must be written after first fetch"


# ---------------------------------------------------------------------------
# fetch_1h_klines: socket-timeout backstop for stale-keepalive hang
# ---------------------------------------------------------------------------


class TestFetch1hKlinesSocketBackstop:
    """Verify that fetch_1h_klines sets the process-wide socket default timeout
    (the stale-keepalive ssl.read hang backstop) on the fetch path."""

    _DATE = dt.date(2024, 3, 1)

    def test_fetch_sets_socket_default_timeout(self, tmp_path):
        """fetch_1h_klines must call socket.setdefaulttimeout(http_timeout_get_secs + 10)
        before the concurrent fetch loop so that stale keep-alive connections can never
        hang indefinitely in ssl.read. Mirrors BinanceSource.__init__ in cli/data/binance.py."""
        symbols = ["BTCUSDT"]
        cache = str(tmp_path / "1h.parquet")
        expected_timeout = FetchConfig().http_timeout_get_secs + 10

        raw = _make_1h_kline_zip(self._DATE, "BTCUSDT")
        mock_resp = MagicMock(status=200)
        mock_resp.data = raw

        with patch.object(_pool, "request", return_value=mock_resp):
            fetch_1h_klines(symbols, self._DATE, self._DATE, cache_path=cache)

        assert socket.getdefaulttimeout() == expected_timeout, (
            f"socket.getdefaulttimeout() should be {expected_timeout} after fetch, got {socket.getdefaulttimeout()}"
        )
