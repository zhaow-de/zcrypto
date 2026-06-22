"""Tests for the perp-spot basis decoder.

No network — all tests use synthetic zips built from known rows.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile

import pytest

from cli.data.basis import parse_basis_zip

D = dt.date(2024, 1, 2)

# Column layout as confirmed by live probe on data.binance.vision (2026-06-22):
# premiumIndexKlines 1d daily archive — same OHLC schema as klines, no header quote marks
_HEADER = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"


def _make_basis_zip(date: dt.date, rows: list[tuple]) -> bytes:
    """Pack header + rows into a Binance-shaped premiumIndexKlines zip for the given date."""
    lines = [_HEADER.rstrip("\n")]
    for r in rows:
        lines.append(",".join(str(x) for x in r))
    csv_text = "\n".join(lines) + "\n"
    inner_name = f"BTCUSDT-1d-{date}.csv"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, csv_text)
    return buf.getvalue()


def _make_one_day_row(date: dt.date, close: float = 0.00070818) -> tuple:
    """One 1d-candle row for the given date (epoch ms open_time)."""
    import calendar

    open_ms = int(calendar.timegm(date.timetuple())) * 1000
    close_ms = open_ms + 86400000 - 1
    return (open_ms, 0.00117148, 0.00387592, -0.00099973, close, 0, close_ms, 0, 17278, 0, 0, 0)


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_parse_basis_zip_returns_single_row():
    zip_bytes = _make_basis_zip(D, [_make_one_day_row(D)])
    df = parse_basis_zip(zip_bytes, "BTCUSDT", D)
    assert len(df) == 1


def test_parse_basis_zip_date_index():
    zip_bytes = _make_basis_zip(D, [_make_one_day_row(D)])
    df = parse_basis_zip(zip_bytes, "BTCUSDT", D)
    assert df.index[0] == D


def test_parse_basis_zip_field_name():
    zip_bytes = _make_basis_zip(D, [_make_one_day_row(D)])
    df = parse_basis_zip(zip_bytes, "BTCUSDT", D)
    assert list(df.columns) == ["$basis"]


def test_parse_basis_zip_close_value():
    """$basis equals the close column from the daily 1d candle."""
    zip_bytes = _make_basis_zip(D, [_make_one_day_row(D, close=0.00070818)])
    df = parse_basis_zip(zip_bytes, "BTCUSDT", D)
    assert df.iloc[0]["$basis"] == pytest.approx(0.00070818)


def test_parse_basis_zip_dtype_float():
    zip_bytes = _make_basis_zip(D, [_make_one_day_row(D)])
    df = parse_basis_zip(zip_bytes, "BTCUSDT", D)
    assert df["$basis"].dtype.kind == "f"


def test_parse_basis_zip_negative_basis():
    """$basis can be negative (perp trades at discount to index)."""
    zip_bytes = _make_basis_zip(D, [_make_one_day_row(D, close=-0.00099973)])
    df = parse_basis_zip(zip_bytes, "BTCUSDT", D)
    assert df.iloc[0]["$basis"] == pytest.approx(-0.00099973)


def test_parse_basis_zip_takes_close_not_open():
    """$basis = close, not open or mean."""
    row = _make_one_day_row(D, close=0.00500000)
    # open is 0.00117148; close is 0.00500000 — they must not be confused
    zip_bytes = _make_basis_zip(D, [row])
    df = parse_basis_zip(zip_bytes, "BTCUSDT", D)
    assert df.iloc[0]["$basis"] == pytest.approx(0.00500000)


# ---------------------------------------------------------------------------
# Graceful error handling
# ---------------------------------------------------------------------------


def test_parse_basis_zip_missing_close_column_raises():
    """A CSV missing the 'close' column raises ValueError."""
    bad_header = "open_time,open,high,low,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
    row = _make_one_day_row(D)
    # Drop the 'close' column (index 4) from the row
    row_without_close = row[:4] + row[5:]
    lines = [bad_header.rstrip("\n"), ",".join(str(x) for x in row_without_close)]
    csv_text = "\n".join(lines) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"BTCUSDT-1d-{D}.csv", csv_text)
    with pytest.raises(ValueError, match="missing column"):
        parse_basis_zip(buf.getvalue(), "BTCUSDT", D)


def test_parse_basis_zip_empty_csv_raises():
    """A zip with only the header (no data rows) raises ValueError."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"BTCUSDT-1d-{D}.csv", _HEADER)
    with pytest.raises(ValueError, match="no data rows"):
        parse_basis_zip(buf.getvalue(), "BTCUSDT", D)


def test_parse_basis_zip_multiple_files_raises():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.csv", "x")
        zf.writestr("b.csv", "x")
    with pytest.raises(ValueError, match="exactly one file"):
        parse_basis_zip(buf.getvalue(), "BTCUSDT", D)
