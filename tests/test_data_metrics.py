"""Tests for the futures metrics decoder (OI + long-short + taker ratio).

No network — all tests use synthetic zips built from known rows.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile

import pytest

from cli.data.metrics import parse_metrics_zip

D = dt.date(2024, 1, 2)

# Column names as confirmed by live probe on data.binance.vision (2026-06-22):
_HEADER = "create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n"


def _make_metrics_zip(date: dt.date, rows: list[tuple]) -> bytes:
    """Pack header + rows into a Binance-shaped metrics zip for the given date."""
    lines = [_HEADER.rstrip("\n")]
    for r in rows:
        lines.append(",".join(str(x) for x in r))
    csv_text = "\n".join(lines) + "\n"
    inner_name = f"BTCUSDT-metrics-{date}.csv"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, csv_text)
    return buf.getvalue()


def _make_5min_rows(
    date: dt.date, oi: float = 80000.0, oi_val: float = 3.5e9, ls_top: float = 1.2, ls_global: float = 1.1, taker: float = 1.0
) -> list[tuple]:
    """Generate 288 synthetic 5-minute rows for the given date with uniform values."""
    rows = []
    for i in range(288):
        h, m = divmod(i * 5, 60)
        ts = f"{date} {h:02d}:{m:02d}:00"
        rows.append((ts, "BTCUSDT", oi, oi_val, ls_global + 0.01, ls_top, ls_global, taker))
    return rows


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_parse_metrics_zip_returns_single_row():
    rows = _make_5min_rows(D)
    zip_bytes = _make_metrics_zip(D, rows)
    df = parse_metrics_zip(zip_bytes, "BTCUSDT", D)
    assert len(df) == 1


def test_parse_metrics_zip_date_index():
    rows = _make_5min_rows(D)
    zip_bytes = _make_metrics_zip(D, rows)
    df = parse_metrics_zip(zip_bytes, "BTCUSDT", D)
    assert df.index[0] == D


def test_parse_metrics_zip_field_names():
    rows = _make_5min_rows(D)
    zip_bytes = _make_metrics_zip(D, rows)
    df = parse_metrics_zip(zip_bytes, "BTCUSDT", D)
    assert set(df.columns) == {"$oi", "$oi_value", "$ls_top", "$ls_global", "$taker_ratio"}


def test_parse_metrics_zip_takes_last_of_day():
    """The single daily row is the LAST-of-day (23:55) snapshot, not the mean."""
    rows = _make_5min_rows(D, oi=70000.0, ls_top=1.20, taker=1.10)
    # Make the final (23:55) snapshot distinct so last-of-day is distinguishable from the mean:
    # row tuple = (ts, symbol, $oi, $oi_value, count_toptrader, $ls_top, $ls_global, $taker_ratio)
    last = rows[-1]
    rows[-1] = (last[0], last[1], 90000.0, last[3], last[4], 1.80, last[6], 2.40)
    zip_bytes = _make_metrics_zip(D, rows)
    df = parse_metrics_zip(zip_bytes, "BTCUSDT", D)
    row = df.iloc[0]
    assert row["$oi"] == pytest.approx(90000.0)  # last row, not the ~70069 mean
    assert row["$ls_top"] == pytest.approx(1.80)  # last row, not ~1.20
    assert row["$taker_ratio"] == pytest.approx(2.40)  # last row, not ~1.10


def test_parse_metrics_zip_dtypes_float():
    rows = _make_5min_rows(D)
    zip_bytes = _make_metrics_zip(D, rows)
    df = parse_metrics_zip(zip_bytes, "BTCUSDT", D)
    for col in df.columns:
        assert df[col].dtype.kind == "f", f"{col} should be float"


def test_parse_metrics_zip_varying_values_uses_last():
    """When values vary across the day, the last-of-day snapshot is taken (not the mean)."""
    # first 144 rows (00:00-11:55) oi=70000, last 144 (12:00-23:55) oi=90000 → last-of-day=90000 (mean would be 80000)
    rows_low = _make_5min_rows(D, oi=70000.0)[:144]
    rows_high = _make_5min_rows(D, oi=90000.0)[144:]
    zip_bytes = _make_metrics_zip(D, rows_low + rows_high)
    df = parse_metrics_zip(zip_bytes, "BTCUSDT", D)
    assert df.iloc[0]["$oi"] == pytest.approx(90000.0, rel=1e-6)


# ---------------------------------------------------------------------------
# Graceful error handling
# ---------------------------------------------------------------------------


def test_parse_metrics_zip_missing_column_raises():
    """A CSV missing a required column raises ValueError (not a KeyError crash)."""
    # Strip one required column from the header
    bad_header = "create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio\n"
    ts = f"{D} 00:00:00"
    csv_text = bad_header + f"{ts},BTCUSDT,80000,3e9,1.1,1.2,1.08\n"
    inner_name = f"BTCUSDT-metrics-{D}.csv"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(inner_name, csv_text)
    with pytest.raises(ValueError, match="missing column"):
        parse_metrics_zip(buf.getvalue(), "BTCUSDT", D)


def test_parse_metrics_zip_empty_csv_raises():
    """A zip containing only the header (no data rows) raises ValueError."""
    csv_text = _HEADER
    inner_name = f"BTCUSDT-metrics-{D}.csv"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(inner_name, csv_text)
    with pytest.raises(ValueError, match="no data rows"):
        parse_metrics_zip(buf.getvalue(), "BTCUSDT", D)


def test_parse_metrics_zip_multiple_files_in_zip_raises():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.csv", "x")
        zf.writestr("b.csv", "x")
    with pytest.raises(ValueError, match="exactly one file"):
        parse_metrics_zip(buf.getvalue(), "BTCUSDT", D)
